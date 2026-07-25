"""Fall Detection — détecte les chutes de personnes par heuristique aspect ratio.

Une personne debout a bbox portrait (h > w). Une personne allongée après chute
a bbox paysage (w > h). En combinant cette heuristique + variation soudaine +
tracking (identité stable pendant plusieurs frames), on obtient un détecteur
raisonnable sans modèle IA dédié.
"""
from __future__ import annotations
import time
from plugin_manager.interfaces import PipelineConsumer, Frame, PipelineResult


class FallDetectionPlugin(PipelineConsumer):
    name = "fall-detection"
    version = "2.0.0"

    def __init__(self):
        # track_id -> {"last_ratio": float, "since": timestamp_fall}
        self._history = {}
        self._alerted = set()

    async def on_load(self, ctx) -> None:
        self._ctx = ctx
        cfg = ctx.config or {}
        # Seuil : ratio h/w — sous cette valeur = personne allongée
        self._fallen_ratio = float(cfg.get("fallen_aspect_ratio", 0.7))
        # Persistance minimale (secondes) avant émission alerte
        self._min_persist = float(cfg.get("min_persist_seconds", 2.0))
        ctx.set_state("ready")

    async def on_config_change(self, new_config: dict) -> None:
        cfg = new_config or {}
        self._fallen_ratio = float(cfg.get("fallen_aspect_ratio", 0.7))
        self._min_persist = float(cfg.get("min_persist_seconds", 2.0))
        self._ctx.set_state("ready")

    async def consume(self, frame: Frame, pipeline: PipelineResult) -> list:
        events = []
        now = time.time()
        persons = [t for t in pipeline.tracks if t.label == "person"]
        seen = set()
        for t in persons:
            seen.add(t.track_id)
            x1, y1, x2, y2 = t.bbox
            w = max(1.0, x2 - x1)
            h = max(1.0, y2 - y1)
            ratio = h / w
            hist = self._history.get(t.track_id, {"since": None})

            if ratio < self._fallen_ratio:
                # Personne semble allongée
                if hist["since"] is None:
                    hist["since"] = now
                elif now - hist["since"] >= self._min_persist and t.track_id not in self._alerted:
                    self._alerted.add(t.track_id)
                    events.append({
                        "type": "alert.critical",
                        "severity": "critical",
                        "message": f"🚑 CHUTE DÉTECTÉE (track {t.track_id})",
                        "data": {
                            "track_id": t.track_id,
                            "bbox": [x1, y1, x2, y2],
                            "aspect_ratio": ratio,
                            "duration_s": round(now - hist["since"], 1),
                            "camera_id": frame.camera_id,
                        },
                    })
            else:
                # La personne s'est relevée
                hist["since"] = None
                self._alerted.discard(t.track_id)
            self._history[t.track_id] = hist

        # Purge tracks disparus
        for tid in list(self._history.keys()):
            if tid not in seen:
                self._history.pop(tid, None)
                self._alerted.discard(tid)

        return events

    async def on_unload(self) -> None:
        pass
