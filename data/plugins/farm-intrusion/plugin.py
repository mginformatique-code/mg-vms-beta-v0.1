"""Farm Intrusion — alerte si une personne/véhicule entre dans une zone
protégée, avec fenêtre horaire optionnelle (nuit).

S'appuie sur les tracks déjà produits par le pipeline (comme occupancy) —
pas de modèle dédié nécessaire.
"""
from __future__ import annotations
import time
from datetime import datetime
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult


def _point_in_polygon(pt, poly):
    """Ray-casting algorithm."""
    x, y = pt
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


class FarmIntrusionPlugin(PipelineConsumer):
    name = "farm-intrusion"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._zone = cfg.get("zone") or [[100, 100], [700, 100], [700, 500], [100, 500]]
        self._labels = set(cfg.get("target_labels") or ["person", "car", "truck", "motorcycle"])
        self._night_only = bool(cfg.get("night_only", False))
        self._night_hour_start = int(cfg.get("night_hour_start", 22))
        self._night_hour_end = int(cfg.get("night_hour_end", 6))
        self._cooldown_s = float(cfg.get("cooldown_s", 60))
        self._inside: set[int] = set()
        self._last_alert: dict[int, float] = {}
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._zone = cfg.get("zone") or [[100, 100], [700, 100], [700, 500], [100, 500]]
        self._labels = set(cfg.get("target_labels") or ["person", "car", "truck", "motorcycle"])
        self._night_only = bool(cfg.get("night_only", False))
        self._night_hour_start = int(cfg.get("night_hour_start", 22))
        self._night_hour_end = int(cfg.get("night_hour_end", 6))
        self._cooldown_s = float(cfg.get("cooldown_s", 60))
        self._inside = set()
        self._last_alert = {}
        self._ctx.set_state("ready")

    def _is_night(self) -> bool:
        h = datetime.now().hour
        if self._night_hour_start >= self._night_hour_end:
            return h >= self._night_hour_start or h < self._night_hour_end
        return self._night_hour_start <= h < self._night_hour_end

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        if self._night_only and not self._is_night():
            return []
        events = []
        now = time.time()
        seen_ids = set()
        for t in pipeline.tracks:
            if t.label not in self._labels:
                continue
            x1, y1, x2, y2 = t.bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if not _point_in_polygon((cx, cy), self._zone):
                continue
            tid = t.track_id
            seen_ids.add(tid)
            if tid not in self._inside:
                self._inside.add(tid)
                last = self._last_alert.get(tid, 0)
                if now - last >= self._cooldown_s:
                    self._last_alert[tid] = now
                    events.append({
                        "type": "intrusion.alert",
                        "severity": "critical",
                        "message": f"Intrusion détectée : {t.label} (track {tid}) dans la zone protégée",
                        "data": {"track_id": tid, "label": t.label},
                    })
        for tid in list(self._inside):
            if tid not in seen_ids:
                self._inside.discard(tid)
        return events

    async def on_unload(self) -> None:
        pass
