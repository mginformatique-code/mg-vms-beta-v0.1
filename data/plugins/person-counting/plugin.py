"""Person Counting — comptage réel de personnes qui traversent une ligne.

Utilise les tracks du pipeline (Tracker + Detector). Chaque track est suivi ;
quand son centroïde traverse la ligne dans un sens, +1 (in ou out).
"""
from __future__ import annotations
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult


def _sign(x):
    return 1 if x > 0 else -1 if x < 0 else 0


def _cross_line(p_prev, p_curr, line_start, line_end):
    """Retourne 'in', 'out' ou None selon direction de traversée."""
    x1, y1 = line_start
    x2, y2 = line_end
    def side(pt):
        return (pt[0] - x1) * (y2 - y1) - (pt[1] - y1) * (x2 - x1)
    s0 = _sign(side(p_prev))
    s1 = _sign(side(p_curr))
    if s0 == 0 or s1 == 0 or s0 == s1:
        return None
    return "in" if s1 > 0 else "out"


class PersonCountingPlugin(PipelineConsumer):
    name = "person-counting"
    version = "2.0.0"

    def __init__(self):
        self._last_pos = {}  # track_id -> (cx, cy)
        self._counted = {}   # track_id -> "in" | "out" (déjà compté ce sens)
        self._count_in = 0
        self._count_out = 0

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        # Ligne par défaut : horizontale au milieu de la frame
        self._line = cfg.get("counting_line") or [[0, 240], [640, 240]]
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        self._line = (new_config or {}).get("counting_line") or [[0, 240], [640, 240]]
        # Reset compteurs sur changement de ligne
        self._last_pos = {}
        self._counted = {}
        self._count_in = 0
        self._count_out = 0
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        events = []
        line_start = tuple(self._line[0])
        line_end = tuple(self._line[1])

        persons = [t for t in pipeline.tracks if t.label == "person"]
        seen_ids = set()
        for t in persons:
            seen_ids.add(t.track_id)
            x1, y1, x2, y2 = t.bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            prev = self._last_pos.get(t.track_id)
            self._last_pos[t.track_id] = (cx, cy)
            if prev is None:
                continue
            direction = _cross_line(prev, (cx, cy), line_start, line_end)
            if direction and self._counted.get(t.track_id) != direction:
                self._counted[t.track_id] = direction
                if direction == "in":
                    self._count_in += 1
                else:
                    self._count_out += 1
                events.append({
                    "type": "counting.person",
                    "severity": "info",
                    "message": f"Personne (track {t.track_id}) → {direction}",
                    "data": {
                        "track_id": t.track_id,
                        "direction": direction,
                        "count_in": self._count_in,
                        "count_out": self._count_out,
                        "occupancy": self._count_in - self._count_out,
                    },
                })

        # Purge les tracks disparus
        for tid in list(self._last_pos.keys()):
            if tid not in seen_ids:
                self._last_pos.pop(tid, None)

        return events

    async def on_unload(self) -> None:
        pass
