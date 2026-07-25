"""Occupancy — compte le nombre de personnes/objets dans une zone polygonale."""
from __future__ import annotations
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


class OccupancyPlugin(PipelineConsumer):
    name = "occupancy"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        # Zone par défaut : rectangle 100,100 → 500,400
        self._zone = cfg.get("zone") or [[100, 100], [500, 100], [500, 400], [100, 400]]
        self._labels = set(cfg.get("target_labels") or ["person"])
        self._max_capacity = int(cfg.get("max_capacity", 999))
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._zone = cfg.get("zone") or [[100, 100], [500, 100], [500, 400], [100, 400]]
        self._labels = set(cfg.get("target_labels") or ["person"])
        self._max_capacity = int(cfg.get("max_capacity", 999))
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        # Compte les tracks (avec identité) ou fallback detections
        items = pipeline.tracks or pipeline.detections
        occupants = []
        for it in items:
            label = getattr(it, "label", "?")
            if label not in self._labels:
                continue
            x1, y1, x2, y2 = it.bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if _point_in_polygon((cx, cy), self._zone):
                occupants.append(label)

        events = [{
            "type": "occupancy.zone",
            "severity": "info",
            "message": f"Occupation zone : {len(occupants)}/{self._max_capacity}",
            "data": {
                "count": len(occupants),
                "capacity": self._max_capacity,
                "over_capacity": len(occupants) > self._max_capacity,
                "labels_count": {lbl: occupants.count(lbl) for lbl in set(occupants)},
            },
        }]
        if len(occupants) > self._max_capacity:
            events.append({
                "type": "occupancy.alert",
                "severity": "warning",
                "message": f"⚠️ Capacité dépassée : {len(occupants)}/{self._max_capacity}",
                "data": {"count": len(occupants), "capacity": self._max_capacity},
            })
        return events

    async def on_unload(self) -> None:
        pass
