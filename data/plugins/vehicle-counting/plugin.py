"""Vehicle Counting — comptage réel de véhicules qui traversent une ligne."""
from __future__ import annotations
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult

VEHICLE_LABELS = {"car", "truck", "motorcycle", "bicycle", "bus"}


def _sign(x):
    return 1 if x > 0 else -1 if x < 0 else 0


def _cross_line(p_prev, p_curr, ls, le):
    def side(pt):
        return (pt[0] - ls[0]) * (le[1] - ls[1]) - (pt[1] - ls[1]) * (le[0] - ls[0])
    s0, s1 = _sign(side(p_prev)), _sign(side(p_curr))
    if s0 == 0 or s1 == 0 or s0 == s1:
        return None
    return "in" if s1 > 0 else "out"


class VehicleCountingPlugin(PipelineConsumer):
    name = "vehicle-counting"
    version = "2.0.0"

    def __init__(self):
        self._last_pos = {}
        self._counted = {}
        self._counts = {}  # label -> {"in": 0, "out": 0}

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._line = cfg.get("counting_line") or [[0, 300], [640, 300]]
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._line = (new_config or {}).get("counting_line") or [[0, 300], [640, 300]]
        self._last_pos, self._counted, self._counts = {}, {}, {}
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        events = []
        ls, le = tuple(self._line[0]), tuple(self._line[1])
        seen = set()
        for t in pipeline.tracks:
            if t.label not in VEHICLE_LABELS:
                continue
            seen.add(t.track_id)
            x1, y1, x2, y2 = t.bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            prev = self._last_pos.get(t.track_id)
            self._last_pos[t.track_id] = (cx, cy)
            if prev is None:
                continue
            direction = _cross_line(prev, (cx, cy), ls, le)
            if direction and self._counted.get(t.track_id) != direction:
                self._counted[t.track_id] = direction
                self._counts.setdefault(t.label, {"in": 0, "out": 0})
                self._counts[t.label][direction] += 1
                events.append({
                    "type": "counting.vehicle",
                    "severity": "info",
                    "message": f"{t.label} (track {t.track_id}) → {direction}",
                    "data": {
                        "track_id": t.track_id, "label": t.label,
                        "direction": direction, "counts": dict(self._counts),
                    },
                })
        for tid in list(self._last_pos.keys()):
            if tid not in seen:
                self._last_pos.pop(tid, None)
        return events

    async def on_unload(self) -> None:
        pass
