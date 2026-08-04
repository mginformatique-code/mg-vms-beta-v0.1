"""Pipeline metrics singleton — monitoring temps réel MG-VMS vNext.

Trace FPS + latences PAR ÉTAPE du pipeline IA par caméra pour le monitoring
temps réel (dashboard AI Monitoring, `/api/diagnostics/pipeline-metrics`).

Étapes tracées (record_stage) :
    - fetch_ms          → récupération frame (go2rtc / frame_source)
    - yolo_ms           → inférence YOLO
    - tracking_ms       → ByteTrack
    - alpr_ms           → fast-alpr local
    - realtime_ms       → total phase A (chemin critique vidéo)
    - downstream_ms     → total phase B (workers plugins/zones/workflows)

Objectifs de perf (1080p) :
    - fps_5s ≥ 20-30
    - realtime_ms < 200
    - tracking_ms < 50
    - drops_5s = 0 en régime normal

Compteurs additionnels :
    - success / errors : dispatch_pipeline OK / KO
    - drops            : frames downstream droppées (backpressure)
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock


class PipelineMetrics:
    """Métriques par caméra, fenêtre glissante 100 cycles."""

    _WINDOW = 100
    _STAGES = ("fetch_ms", "yolo_ms", "tracking_ms", "alpr_ms",
               "realtime_ms", "downstream_ms")

    def __init__(self):
        self._per_cam: dict[str, dict] = {}
        self._lock = Lock()

    # ── Legacy API (record global pipeline_ms) ──────────────────────
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

    # ── Nouveau : per-stage timing ─────────────────────────────────
    def record_stage(self, camera_id: str, stage: str, ms: float) -> None:
        """Enregistre la latence d'une étape (yolo_ms, tracking_ms, ...)."""
        if stage not in self._STAGES:
            return
        with self._lock:
            s = self._per_cam.setdefault(camera_id, self._empty())
            s["stages"][stage].append(float(ms))
            if stage == "realtime_ms":
                # Chaque frame temps réel = 1 tick FPS (chemin critique vidéo)
                s["frame_ts"].append(time.time())

    def record_drop(self, camera_id: str) -> None:
        """Compteur des frames downstream droppées (backpressure)."""
        with self._lock:
            s = self._per_cam.setdefault(camera_id, self._empty())
            s["drops"] += 1
            s["drop_ts"].append(time.time())

    # ── Snapshot ────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            out = {}
            now = time.time()
            for cid, s in self._per_cam.items():
                fps_ts = [t for t in s["frame_ts"] if now - t < 5.0]
                drop_ts = [t for t in s["drop_ts"] if now - t < 5.0]
                lat = list(s["latencies"])
                stage_stats = {}
                for stage in self._STAGES:
                    vals = list(s["stages"][stage])
                    if not vals:
                        stage_stats[stage] = {"avg": 0.0, "max": 0.0, "p95": None}
                        continue
                    ordered = sorted(vals)
                    p95_idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
                    stage_stats[stage] = {
                        "avg": round(sum(vals) / len(vals), 1),
                        "max": round(max(vals), 1),
                        "p95": round(ordered[p95_idx], 1) if len(vals) >= 5 else None,
                    }
                out[cid] = {
                    "fps_5s": round(len(fps_ts) / 5.0, 1),
                    "drops_5s": len(drop_ts),
                    "pipeline_ms_avg": round(sum(lat) / len(lat), 1) if lat else 0.0,
                    "pipeline_ms_max": round(max(lat), 1) if lat else 0.0,
                    "pipeline_ms_p95": round(sorted(lat)[int(len(lat) * 0.95)], 1) if len(lat) >= 20 else None,
                    "success_count": s["success"],
                    "error_count": s["errors"],
                    "drop_count": s["drops"],
                    "last_plugins": s["last_plugins"],
                    "stages": stage_stats,
                }
            return out

    def _empty(self) -> dict:
        return {
            "latencies": deque(maxlen=self._WINDOW),
            "frame_ts": deque(maxlen=self._WINDOW),
            "drop_ts": deque(maxlen=self._WINDOW),
            "stages": {stage: deque(maxlen=self._WINDOW) for stage in self._STAGES},
            "success": 0,
            "errors": 0,
            "drops": 0,
            "last_plugins": {},
        }


pipeline_metrics = PipelineMetrics()
