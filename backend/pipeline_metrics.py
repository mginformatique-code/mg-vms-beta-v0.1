"""Pipeline metrics singleton — monitoring temps réel (bug fix Feb 2026).

Trace FPS + latence pipeline par caméra pour le monitoring IA.
Utilisé par `/api/diagnostics/pipeline-metrics`.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock


class PipelineMetrics:
    """Métriques par caméra, agrégées sur les 100 derniers cycles."""

    _WINDOW = 100

    def __init__(self):
        self._per_cam: dict[str, dict] = {}
        self._lock = Lock()

    def record(self, camera_id: str, pipeline_ms: float,
               plugins_used: dict | None = None) -> None:
        with self._lock:
            s = self._per_cam.setdefault(camera_id, self._empty())
            s["latencies"].append(pipeline_ms)
            s["frame_ts"].append(time.time())
            s["success"] += 1
            if plugins_used:
                s["last_plugins"] = plugins_used

    def record_error(self, camera_id: str, pipeline_ms: float) -> None:
        with self._lock:
            s = self._per_cam.setdefault(camera_id, self._empty())
            s["latencies"].append(pipeline_ms)
            s["errors"] += 1

    def snapshot(self) -> dict:
        with self._lock:
            out = {}
            now = time.time()
            for cid, s in self._per_cam.items():
                lat = list(s["latencies"])
                fps_ts = [t for t in s["frame_ts"] if now - t < 5.0]
                fps = len(fps_ts) / 5.0 if fps_ts else 0.0
                out[cid] = {
                    "fps_5s": round(fps, 1),
                    "pipeline_ms_avg": round(sum(lat) / len(lat), 1) if lat else 0.0,
                    "pipeline_ms_max": round(max(lat), 1) if lat else 0.0,
                    "pipeline_ms_p95": round(sorted(lat)[int(len(lat) * 0.95)], 1) if len(lat) >= 20 else None,
                    "success_count": s["success"],
                    "error_count": s["errors"],
                    "last_plugins": s["last_plugins"],
                }
            return out

    def _empty(self) -> dict:
        return {
            "latencies": deque(maxlen=self._WINDOW),
            "frame_ts": deque(maxlen=self._WINDOW),
            "success": 0,
            "errors": 0,
            "last_plugins": {},
        }


pipeline_metrics = PipelineMetrics()
