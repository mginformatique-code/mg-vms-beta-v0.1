"""Queue Detection — longueur de file d'attente + temps d'attente moyen.

Approximation par comptage + temps de présence dans une zone dédiée (pas
de détection de posture/formation de file — s'appuie sur les tracks déjà
produits par le pipeline, comme occupancy/dwell-time).
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


class QueueDetectionPlugin(PipelineConsumer):
    name = "queue-detection"
    version = "2.0.0"

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        self._zone = cfg.get("zone") or [[100, 100], [500, 100], [500, 400], [100, 400]]
        self._alert_threshold = int(cfg.get("alert_threshold", 5))
        self._report_interval_s = float(cfg.get("report_interval_s", 30))
        self._entered_at: dict[int, float] = {}
        self._last_report = time.time()
        self._last_reported_length = -1   # -1 = jamais rapporté, force le 1er événement
        self._was_over = False
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._zone = cfg.get("zone") or [[100, 100], [500, 100], [500, 400], [100, 400]]
        self._alert_threshold = int(cfg.get("alert_threshold", 5))
        self._report_interval_s = float(cfg.get("report_interval_s", 30))
        self._entered_at = {}
        self._last_report = time.time()
        self._last_reported_length = -1
        self._was_over = False
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        now = time.time()
        seen_ids = set()
        for t in pipeline.tracks:
            if t.label != "person":
                continue
            x1, y1, x2, y2 = t.bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if not _point_in_polygon((cx, cy), self._zone):
                continue
            seen_ids.add(t.track_id)
            self._entered_at.setdefault(t.track_id, now)

        for tid in list(self._entered_at.keys()):
            if tid not in seen_ids:
                self._entered_at.pop(tid, None)

        queue_length = len(seen_ids)
        avg_wait = (sum(now - t0 for t0 in self._entered_at.values()) / queue_length) if queue_length else 0.0

        events = []
        is_over = queue_length >= self._alert_threshold
        if is_over and not self._was_over:
            events.append({
                "type": "queue.alert",
                "severity": "warning",
                "message": f"File d'attente longue : {queue_length} personne(s), attente moy. {int(avg_wait)}s",
                "data": {"queue_length": queue_length, "avg_wait_sec": int(avg_wait)},
            })
        self._was_over = is_over

        # Émet uniquement si la longueur a CHANGÉ depuis le dernier rapport
        # (avant ce fix : un heartbeat toutes les report_interval_s peu importe
        # l'état — sur une caméra où personne ne traverse jamais la zone,
        # "File d'attente : 0 personne(s)" en boucle, pure pollution de la
        # galerie Événements). report_interval_s plafonne maintenant la
        # fréquence max en cas de changement fréquent, plus un heartbeat fixe.
        if queue_length != self._last_reported_length and now - self._last_report >= min(self._report_interval_s, 5.0):
            self._last_report = now
            self._last_reported_length = queue_length
            events.append({
                "type": "queue.status",
                "severity": "info",
                "message": f"File d'attente : {queue_length} personne(s), attente moy. {int(avg_wait)}s",
                "data": {"queue_length": queue_length, "avg_wait_sec": int(avg_wait)},
            })
        return events

    async def on_unload(self) -> None:
        pass
