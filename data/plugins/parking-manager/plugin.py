"""Parking Manager — occupation de place par zone + durée.

Chaque place est une zone polygonale dédiée : occupée si le centre d'un
véhicule détecté y tombe. Émet un événement à chaque changement d'état
(libre → occupée / occupée → libre) avec la durée de l'état précédent.
Pas de reconnaissance PMR/VIP pour cette v2 réelle (nécessiterait une
signalétique dédiée) — occupation + durée, sans modèle supplémentaire,
s'appuie sur les détections véhicule déjà produites par le pipeline.
"""
from __future__ import annotations
import time
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult

VEHICLE_LABELS = {"car", "truck", "motorcycle", "bus"}


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


class ParkingManagerPlugin(PipelineConsumer):
    name = "parking-manager"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        # spots : [{"id": "P1", "zone": [[x,y], ...]}, ...]
        self._spots = cfg.get("spots") or [
            {"id": "P1", "zone": [[100, 100], [300, 100], [300, 300], [100, 300]]},
        ]
        self._labels = set(cfg.get("target_labels") or VEHICLE_LABELS)
        self._state = {s["id"]: {"occupied": False, "since": time.time()} for s in self._spots}
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._spots = cfg.get("spots") or [
            {"id": "P1", "zone": [[100, 100], [300, 100], [300, 300], [100, 300]]},
        ]
        self._labels = set(cfg.get("target_labels") or VEHICLE_LABELS)
        self._state = {s["id"]: {"occupied": False, "since": time.time()} for s in self._spots}
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        items = pipeline.tracks or pipeline.detections
        centers = []
        for it in items:
            label = getattr(it, "label", "?")
            if label not in self._labels:
                continue
            x1, y1, x2, y2 = it.bbox
            centers.append(((x1 + x2) / 2, (y1 + y2) / 2))

        events = []
        now = time.time()
        for spot in self._spots:
            sid = spot["id"]
            occupied = any(_point_in_polygon(c, spot["zone"]) for c in centers)
            st = self._state.setdefault(sid, {"occupied": False, "since": now})
            if occupied != st["occupied"]:
                duration = now - st["since"]
                events.append({
                    "type": "parking.occupied" if occupied else "parking.freed",
                    "severity": "info",
                    "message": f"Place {sid} : {'occupée' if occupied else 'libérée'} (état précédent {int(duration)}s)",
                    "data": {"spot_id": sid, "occupied": occupied, "previous_state_sec": int(duration)},
                })
                st["occupied"] = occupied
                st["since"] = now
        return events

    async def on_unload(self) -> None:
        pass
