"""Smart Zones — Evaluator engine (P3, Feb 2026).

Reçoit le résultat pipeline (détections + tracks) et évalue toutes les zones
actives pour cette caméra. Pour chaque zone :
- Filtre les détections dans le polygone
- Filtre par classes acceptées + confidence min
- Détecte les transitions ENTER / PRESENT / EXIT via `track_id`
- Applique cooldown + min_dwell
- Déclenche les actions configurées

État en mémoire par zone (survit à la vie du process, restart = reset).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from smart_zones.actuators import dispatch_action

logger = logging.getLogger("smart_zones.engine")


@dataclass
class _ZoneState:
    """État runtime par zone."""
    last_triggered_at: float = 0.0
    trigger_count: int = 0
    # track_id → {first_seen, last_seen}
    tracks_in_zone: dict = field(default_factory=dict)


class SmartZonesEngine:
    """Singleton — évalue les zones à chaque cycle pipeline."""

    def __init__(self):
        # zone_id → _ZoneState
        self._states: dict[str, _ZoneState] = {}
        # cache DB : zone_id → zone_dict (reload périodique)
        self._zones_cache: list[dict] = []
        self._cache_ts: float = 0
        self._cache_ttl_s: float = 15.0

    async def _load_zones(self) -> list[dict]:
        """Cache 15s pour éviter d'aller taper la DB à chaque frame."""
        now = time.time()
        if now - self._cache_ts < self._cache_ttl_s and self._zones_cache:
            return self._zones_cache
        try:
            from database import db
            self._zones_cache = await db.smart_zones.find(
                {"enabled": True}, {"_id": 0},
            ).to_list(500)
            self._cache_ts = now
        except Exception as e:
            logger.warning("smart_zones.load_error err=%s", e)
        return self._zones_cache

    def invalidate_cache(self) -> None:
        """Appelée par les endpoints CRUD après création/modif/suppression."""
        self._cache_ts = 0

    async def evaluate(self, camera_id: str, detections: list, tracks: list,
                       plate_readings: list | None = None) -> list[dict]:
        """Évalue toutes les zones actives pour cette caméra. Retourne les événements.

        `detections` : liste [{class, confidence, bbox=(x,y,w,h)}]
        `tracks` : liste [{track_id, bbox, class}]
        `plate_readings` : optionnel — liste [{plate, confidence, bbox}]
        """
        zones = await self._load_zones()
        events = []
        for zone in zones:
            if zone.get("camera_id") != camera_id:
                continue
            zid = zone["id"]
            st = self._states.setdefault(zid, _ZoneState())
            events.extend(await self._eval_one(zone, st, detections, tracks, plate_readings or []))
        return events

    async def _eval_one(self, zone: dict, st: _ZoneState,
                         detections: list, tracks: list,
                         plates: list) -> list[dict]:
        detect_cfg = zone.get("detect", {}) or {}
        classes = set(detect_cfg.get("classes") or [])
        min_conf = float(detect_cfg.get("min_confidence") or 0.5)
        min_dwell = float(detect_cfg.get("min_dwell_seconds") or 0)
        cooldown = float(detect_cfg.get("cooldown_seconds") or 0)
        trigger_on = set(zone.get("trigger_on") or ["enter"])
        polygon = zone.get("polygon") or []
        now = time.time()

        # Cooldown global : si trigger récent, on ne re-trigger pas
        if cooldown > 0 and (now - st.last_triggered_at) < cooldown:
            # On met à jour l'état mais on n'émet rien
            return []

        # Filtre "in-zone" via tracks (si dispo) sinon detections
        source = tracks or [{"track_id": f"det-{i}", "bbox": d.get("bbox"), "class": d.get("class"),
                              "confidence": d.get("confidence", 0.5)}
                             for i, d in enumerate(detections)]

        in_zone: dict[Any, dict] = {}  # track_id → item
        for item in source:
            klass = item.get("class") or ""
            conf = float(item.get("confidence") or 0.5)
            if classes and klass not in classes:
                # Match "plate:*" contre les plates lues
                if not any(c.startswith("plate:") for c in classes):
                    continue
            if conf < min_conf:
                continue
            bbox = item.get("bbox")
            if not bbox:
                continue
            if polygon and not self._bbox_in_polygon(bbox, polygon):
                continue
            in_zone[item.get("track_id")] = item

        # Match plates si demandé
        if any(c.startswith("plate:") for c in classes) and plates:
            wanted = {c.split(":", 1)[1].upper() for c in classes if c.startswith("plate:")}
            for pr in plates:
                plate = (pr.get("plate") or "").upper()
                if "*" in wanted or plate in wanted:
                    if float(pr.get("confidence") or 0) >= min_conf:
                        in_zone[f"plate:{plate}"] = {"track_id": f"plate:{plate}",
                                                     "class": f"plate:{plate}",
                                                     "confidence": pr.get("confidence")}

        # Comparaison à l'état précédent
        prev_ids = set(st.tracks_in_zone.keys())
        curr_ids = set(in_zone.keys())
        newly_entered = curr_ids - prev_ids
        exited = prev_ids - curr_ids
        events: list[dict] = []

        # ENTER
        for tid in newly_entered:
            st.tracks_in_zone[tid] = {"first_seen": now, "last_seen": now}
            if "enter" in trigger_on:
                # Vérifie min_dwell : trigger différé jusqu'à dwell atteint
                if min_dwell <= 0:
                    ev = await self._trigger(zone, st, in_zone[tid], "enter", now)
                    events.append(ev)

        # PRESENT (dwell)
        for tid in curr_ids & prev_ids:
            st.tracks_in_zone[tid]["last_seen"] = now
            dwell = now - st.tracks_in_zone[tid]["first_seen"]
            if "enter" in trigger_on and min_dwell > 0:
                # Si dwell juste franchi
                already = st.tracks_in_zone[tid].get("triggered", False)
                if not already and dwell >= min_dwell:
                    st.tracks_in_zone[tid]["triggered"] = True
                    ev = await self._trigger(zone, st, in_zone[tid], "enter", now)
                    events.append(ev)
            if "present" in trigger_on:
                ev = await self._trigger(zone, st, in_zone[tid], "present", now, silent=True)
                # Pas d'action pour "present" en continu — juste tracking

        # EXIT
        for tid in exited:
            info = st.tracks_in_zone.pop(tid, {})
            if "exit" in trigger_on:
                ev = await self._trigger(zone, st,
                    {"track_id": tid, "class": "unknown", "confidence": 0.0},
                    "exit", now, extra={"dwell_seconds": int(now - info.get("first_seen", now))})
                events.append(ev)

        return events

    async def _trigger(self, zone: dict, st: _ZoneState, item: dict,
                        event_kind: str, now: float,
                        silent: bool = False, extra: dict | None = None) -> dict:
        """Exécute les actions et met à jour l'état. Retourne un dict événement."""
        if not silent:
            st.last_triggered_at = now
            st.trigger_count += 1
        context = {
            "zone_name": zone.get("name"),
            "zone_id": zone.get("id"),
            "camera_id": zone.get("camera_id"),
            "event_kind": event_kind,
            "track_id": item.get("track_id"),
            "class": item.get("class"),
            "confidence": item.get("confidence"),
            "timestamp": _iso(now),
            **(extra or {}),
        }
        action_results = []
        if not silent:
            for action in zone.get("actions") or []:
                action_results.append(await dispatch_action(action, context))
            # Persist trigger count (best-effort)
            asyncio.create_task(self._persist_trigger(zone["id"], now))
        return {
            "type": f"zone.{event_kind}",
            "severity": "info",
            "message": f"Zone '{zone.get('name')}' — {event_kind} ({item.get('class')})",
            "data": {**context, "actions": action_results},
        }

    async def _persist_trigger(self, zone_id: str, now: float) -> None:
        try:
            from database import db
            await db.smart_zones.update_one(
                {"id": zone_id},
                {"$set": {"last_triggered_at": _iso(now)}, "$inc": {"trigger_count": 1}},
            )
        except Exception:
            pass

    @staticmethod
    def _bbox_in_polygon(bbox, polygon: list[list[float]]) -> bool:
        """Point-in-polygon (ray-casting) sur le centre de bbox.
        Accepte polygon en coords relatives [0..1] OU absolues (retourne True si polygon vide)."""
        if not polygon:
            return True
        x, y, w, h = bbox
        cx = x + w / 2
        cy = y + h / 2
        # Détection auto abs/rel : si tous les points ≤ 1, mode relatif → suppose bbox relatif aussi
        rel = all(0 <= p[0] <= 1 and 0 <= p[1] <= 1 for p in polygon)
        if rel and (cx > 1 or cy > 1):
            # bbox absolu, polygon relatif → on ne peut pas comparer, retourne True (sécurité)
            return True
        # Ray casting
        inside = False
        n = len(polygon)
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            intersect = ((yi > cy) != (yj > cy)) and (
                cx < (xj - xi) * (cy - yi) / (yj - yi + 1e-9) + xi
            )
            if intersect:
                inside = not inside
            j = i
        return inside


def _iso(t: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


engine = SmartZonesEngine()
