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

    # v3.40 · Stationnement natif (dwell par plaque) — indépendant des
    # zones configurées manuellement en DB. Voir track_plate_dwell().
    #
    # v3.42 · Correctif faux-positif signalé en prod (véhicule EN MOUVEMENT
    # affiché "en stationnement depuis 2 min") : la v3.40 dérivait le dwell
    # du simple ÉCART DE TEMPS entre 2 lectures ANPR de la même plaque —
    # un véhicule qui repasse deux fois devant la caméra en moins de
    # _PARKING_GRACE_S (demi-tour, file d'attente, aller-retour) déclenchait
    # le badge sans jamais s'être réellement arrêté. Le dwell dérive
    # désormais de l'IMMOBILITÉ RÉELLE du track_id associé à la plaque
    # (voir track_vehicle_stillness/get_track_stillness ci-dessous) — la
    # même ROI véhicule d'où l'OCR a extrait la plaque (camera_worker.py::
    # _stage_anpr, `p["track_id"] = roi.track_id`), donc pas de 2e système
    # de tracking ni de nouvelle dépendance.
    _PARKING_GRACE_S = 180.0
    _PARKING_MIN_DWELL_S = 120.0
    # Déplacement du centre de bbox (coords normalisées 0..1) au-delà duquel
    # un track_id est considéré "en mouvement" plutôt que "immobile" —
    # première valeur raisonnable, pas encore calibrée sur des mesures
    # terrain (à ajuster si des stationnements réels sont ratés/faux positifs).
    _STILL_MOVE_THRESHOLD_NORM = 0.02
    # Tolérance d'absence dans overlay_boxes avant d'oublier un track_id —
    # nettement plus courte que _PARKING_GRACE_S car les cycles de
    # détection (chaque appel run_downstream) sont bien plus fréquents que
    # les lectures ANPR elles-mêmes.
    _STILL_GRACE_S = 30.0

    def __init__(self):
        # zone_id → _ZoneState
        self._states: dict[str, _ZoneState] = {}
        # cache DB : zone_id → zone_dict (reload périodique)
        self._zones_cache: list[dict] = []
        self._cache_ts: float = 0
        self._cache_ttl_s: float = 15.0
        # camera_id → track_id → {anchor_cx, anchor_cy, still_since, last_seen}
        self._track_stillness: dict[str, dict] = {}
        # camera_id → plate → {track_id, last_anpr_seen}
        self._plate_track_map: dict[str, dict[str, dict]] = {}
        # v3.27 · Occupation zones de stationnement (polygone + capacité) —
        # camera_id → [zone_dict] (cache DB) ; zone_id → {track_id → {since, plate}}
        self._parking_zones: dict[str, list[dict]] = {}
        self._parking_zones_ts: float = 0.0
        self._zone_occupancy: dict[str, dict] = {}

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

    def track_vehicle_stillness(self, camera_id: str, overlay_boxes: list) -> None:
        """Suit l'immobilité RÉELLE (position bbox) de chaque track_id vu ce
        cycle — indépendant de l'ANPR, alimenté à chaque cycle pipeline
        (`result["overlay_boxes"]`, déjà normalisé 0..1 par
        camera_worker.py). C'est CE signal, pas le texte de la plaque, qui
        détermine si un véhicule est réellement garé (voir
        track_plate_dwell). L'ancre de position (anchor_cx/cy) est celle du
        DÉBUT de l'immobilité — comparer au dernier point à chaque cycle
        laisserait une dérive lente (petit mouvement à chaque frame, jamais
        au-dessus du seuil individuellement) passer inaperçue indéfiniment.
        """
        now = time.time()
        cam_state = self._track_stillness.setdefault(camera_id, {})
        seen = set()
        for b in overlay_boxes:
            tid = b.get("track_id")
            bn = b.get("bbox_norm")
            if tid is None or not bn or len(bn) != 4:
                continue
            x1, y1, x2, y2 = bn
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            seen.add(tid)
            st = cam_state.get(tid)
            if st is None:
                cam_state[tid] = {"anchor_cx": cx, "anchor_cy": cy, "still_since": now, "last_seen": now}
                continue
            moved = (abs(cx - st["anchor_cx"]) > self._STILL_MOVE_THRESHOLD_NORM
                     or abs(cy - st["anchor_cy"]) > self._STILL_MOVE_THRESHOLD_NORM)
            if moved:
                # Nouvelle ancre — le véhicule bouge, l'immobilité (si elle
                # reprend) recompte depuis maintenant.
                cam_state[tid] = {"anchor_cx": cx, "anchor_cy": cy, "still_since": now, "last_seen": now}
            else:
                st["last_seen"] = now
        stale = [tid for tid, st in cam_state.items()
                 if tid not in seen and (now - st["last_seen"]) > self._STILL_GRACE_S]
        for tid in stale:
            cam_state.pop(tid, None)

    def get_track_stillness(self, camera_id: str, track_id) -> dict | None:
        """None si ce track_id n'est pas actuellement suivi comme immobile
        (en mouvement, sorti du cadre, ou jamais vu) — sinon
        {"still_since": epoch}."""
        if track_id is None:
            return None
        st = self._track_stillness.get(camera_id, {}).get(track_id)
        if not st:
            return None
        return {"still_since": st["still_since"]}

    def track_plate_dwell(self, camera_id: str, plates: list[dict]) -> None:
        """Associe chaque plaque lue ce cycle à son track_id — CETTE
        fonction ne calcule PLUS le dwell elle-même (v3.42, voir le
        commentaire de classe) : elle mémorise juste "cette plaque = ce
        track_id en ce moment" (`p["track_id"]` vient de la même ROI
        véhicule que l'OCR, camera_worker.py::_stage_anpr). Le dwell réel
        est dérivé EN LECTURE (snapshot_plate_dwell) de l'immobilité live du
        track_id — toujours à jour, se corrige immédiatement si le véhicule
        redémarre, jamais de désynchronisation entre 2 lectures ANPR.
        """
        now = time.time()
        cam_map = self._plate_track_map.setdefault(camera_id, {})
        seen = set()
        for p in plates:
            plate = (p.get("plate") or "").upper().strip()
            tid = p.get("track_id")
            if not plate or tid is None:
                continue
            seen.add(plate)
            cam_map[plate] = {"track_id": tid, "last_anpr_seen": now}
        # Oublie l'association plaque→track_id si l'ANPR ne l'a plus
        # reconfirmée depuis _PARKING_GRACE_S — l'immobilité elle-même reste
        # suivie indépendamment tant que le track existe dans overlay_boxes.
        stale = [pl for pl, st in cam_map.items()
                 if pl not in seen and (now - st["last_anpr_seen"]) > self._PARKING_GRACE_S]
        for pl in stale:
            cam_map.pop(pl, None)

    def snapshot_plate_dwell(self) -> dict:
        """Lecture — état courant dwell par plaque/caméra (API-side, via
        pipeline_snapshot.py). Le dwell est calculé ICI, au moment de la
        lecture, à partir de l'immobilité live du track_id associé — pas
        d'un compteur incrémenté au fil des cycles pipeline."""
        now = time.time()
        cameras: dict[str, dict] = {}
        for cam_id, plates in self._plate_track_map.items():
            cam_out = {}
            for plate, link in plates.items():
                stillness = self.get_track_stillness(cam_id, link["track_id"])
                if stillness is None:
                    continue  # véhicule associé pas (plus) suivi comme immobile
                dwell = now - stillness["still_since"]
                cam_out[plate] = {
                    "first_seen": _iso(stillness["still_since"]),
                    "last_seen": _iso(now),
                    "dwell_seconds": int(dwell),
                    "parked": dwell >= self._PARKING_MIN_DWELL_S,
                }
            if cam_out:
                cameras[cam_id] = cam_out
        return {
            "cameras": cameras,
            "min_dwell_seconds": int(self._PARKING_MIN_DWELL_S),
            "grace_seconds": int(self._PARKING_GRACE_S),
        }

    # ═══════════════════════════════════════════════════════════════
    # v3.27 · Comptage d'occupation par zone de stationnement (polygone +
    # capacité, db.parking_zones) — demande explicite : "système hybride qui
    # combine un véhicule fixe [immobile] et un véhicule fixe dans un
    # polygone". Le plugin "Zones de stationnement" (Administration →
    # Plugins) n'était jusqu'ici qu'un éditeur de zones (polygone +
    # capacité) SANS AUCUN moteur de comptage réel derrière — ceci comble ce
    # trou. Réutilise le MÊME signal d'immobilité que le dwell par plaque
    # ci-dessus (get_track_stillness) : un véhicule simplement DE PASSAGE
    # dans le polygone ne compte pas comme "occupant une place", seul un
    # véhicule réellement immobile compte — sinon une voiture qui traverse
    # le polygone en roulant ferait clignoter le comptage.
    # ═══════════════════════════════════════════════════════════════
    _PARKING_ZONES_CACHE_TTL_S = 30.0

    async def refresh_parking_zones(self) -> None:
        """Cache 30s — évite d'aller taper la DB à chaque frame pour une
        config qui ne change quasiment jamais."""
        now = time.time()
        if now - self._parking_zones_ts < self._PARKING_ZONES_CACHE_TTL_S and self._parking_zones:
            return
        try:
            from database import db
            zones = await db.parking_zones.find({}, {"_id": 0}).to_list(500)
        except Exception as e:
            logger.warning("parking_zones.load_error err=%s", e)
            return
        by_cam: dict[str, list[dict]] = {}
        for z in zones:
            by_cam.setdefault(z.get("camera_id"), []).append(z)
        self._parking_zones = by_cam
        self._parking_zones_ts = now

    def track_zone_occupancy(self, camera_id: str, overlay_boxes: list) -> None:
        """Un appel par cycle pipeline (même cadence que track_vehicle_
        stillness/track_plate_dwell ci-dessus, mêmes overlay_boxes) — DOIT
        être appelé APRÈS track_vehicle_stillness dans le même cycle pour
        lire une immobilité à jour."""
        zones = self._parking_zones.get(camera_id) or []
        if not zones:
            return
        plate_by_track = {v["track_id"]: p for p, v in self._plate_track_map.get(camera_id, {}).items()}
        for zone in zones:
            zid = zone["id"]
            polygon = zone.get("polygon") or []
            occ = self._zone_occupancy.setdefault(zid, {})
            seen_here = set()
            for b in overlay_boxes:
                tid = b.get("track_id")
                bn = b.get("bbox_norm")
                if tid is None or not bn or len(bn) != 4:
                    continue
                x1, y1, x2, y2 = bn
                if not self._bbox_in_polygon((x1, y1, x2 - x1, y2 - y1), polygon):
                    continue
                stillness = self.get_track_stillness(camera_id, tid)
                if stillness is None:
                    continue  # présent mais en mouvement — ne compte pas comme "garé"
                seen_here.add(tid)
                if tid in occ:
                    occ[tid]["plate"] = plate_by_track.get(tid) or occ[tid].get("plate")
                else:
                    occ[tid] = {"since": stillness["still_since"], "plate": plate_by_track.get(tid)}
            for tid in [t for t in occ if t not in seen_here]:
                occ.pop(tid, None)

    def snapshot_zone_occupancy(self) -> dict:
        """Lecture — occupation live par zone, calculée à partir de
        l'immobilité live du moment (pas d'un compteur incrémenté)."""
        out: dict[str, dict] = {}
        for cam_id, zones in self._parking_zones.items():
            for zone in zones:
                zid = zone["id"]
                occ = self._zone_occupancy.get(zid) or {}
                out[zid] = {
                    "camera_id": cam_id,
                    "name": zone.get("name"),
                    "capacity": zone.get("capacity"),
                    "occupied": len(occ),
                    "vehicles": [{"plate": v.get("plate"), "since": _iso(v["since"])} for v in occ.values()],
                }
        return out

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
