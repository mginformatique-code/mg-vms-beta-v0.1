"""Dwell Time — mesure le temps passé par un objet suivi dans une zone.

Alerte quand un track (personne par défaut) reste plus longtemps que le
seuil configuré dans la zone — utile pour repérer un rôdage prolongé
(vitrine, rayon) sans avoir besoin d'un modèle dédié : s'appuie sur les
tracks déjà produits par le pipeline (Detector + Tracker), comme occupancy.
"""
from __future__ import annotations
import time
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


class DwellTimePlugin(PipelineConsumer):
    name = "dwell-time"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._zone = cfg.get("zone") or [[100, 100], [500, 100], [500, 400], [100, 400]]
        self._labels = set(cfg.get("target_labels") or ["person"])
        self._alert_after_s = float(cfg.get("alert_after_s", 30))
        self._entered_at: dict[int, float] = {}   # track_id -> entrée dans la zone
        self._alerted: set[int] = set()            # track_id déjà signalés pour ce séjour
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._zone = cfg.get("zone") or [[100, 100], [500, 100], [500, 400], [100, 400]]
        self._labels = set(cfg.get("target_labels") or ["person"])
        self._alert_after_s = float(cfg.get("alert_after_s", 30))
        self._entered_at = {}
        self._alerted = set()
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
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
            if tid not in self._entered_at:
                self._entered_at[tid] = now
            dwell = now - self._entered_at[tid]
            if dwell >= self._alert_after_s and tid not in self._alerted:
                self._alerted.add(tid)
                events.append({
                    "type": "dwell.alert",
                    "severity": "warning",
                    "message": f"{t.label} présent {int(dwell)}s dans la zone (track {tid})",
                    "data": {"track_id": tid, "label": t.label, "dwell_sec": int(dwell)},
                })

        # Tracks sortis de la zone (ou disparus) : on repart de zéro pour eux
        for tid in list(self._entered_at.keys()):
            if tid not in seen_ids:
                self._entered_at.pop(tid, None)
                self._alerted.discard(tid)

        return events

    async def on_unload(self) -> None:
        pass
