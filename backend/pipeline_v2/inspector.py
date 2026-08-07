"""Pipeline v2 · PipelineInspector — diagnostic runtime par caméra et par stage.

Pour chaque caméra × stage : temps moyen / max / dernier, appels, erreurs,
timeouts, FPS effectif. Snapshot système : CPU, RAM, GPU, VRAM.
Exposé via ``GET /api/diagnostics/pipeline-inspector``.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Optional

STAGE_ORDER = ["fetch", "decode", "motion", "yolo", "tracking", "roi", "anpr",
               "dispatch", "multi_anpr", "scenarios", "persist", "websocket",
               "downstream"]


class _StageStat:
    __slots__ = ("count", "errors", "timeouts", "sum_ms", "max_ms", "last_ms", "window")

    def __init__(self):
        self.count = 0
        self.errors = 0
        self.timeouts = 0
        self.sum_ms = 0.0
        self.max_ms = 0.0
        self.last_ms = 0.0
        self.window: deque = deque(maxlen=300)  # (ts, ms)

    def record(self, ms: float, error: bool = False, timeout: bool = False):
        self.count += 1
        self.sum_ms += ms
        self.last_ms = ms
        if ms > self.max_ms:
            self.max_ms = ms
        if error:
            self.errors += 1
        if timeout:
            self.timeouts += 1
        self.window.append((time.time(), ms))

    def to_dict(self) -> dict:
        n = self.count or 1
        # Moyenne fenêtre glissante (60 s) — plus fidèle que la moyenne globale
        cutoff = time.time() - 60
        recent = [ms for ts, ms in self.window if ts >= cutoff]
        # v0.7.g · Axe 1+2 · Percentiles p50/p95/p99 sur la fenêtre 60s
        p50 = p95 = p99 = 0.0
        if recent:
            s = sorted(recent)
            def _pct(p):
                k = max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))
                return round(s[k], 2)
            p50, p95, p99 = _pct(0.50), _pct(0.95), _pct(0.99)
        return {
            "calls": self.count,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "avg_ms": round(self.sum_ms / n, 2),
            "avg_ms_60s": round(sum(recent) / len(recent), 2) if recent else 0.0,
            "max_ms": round(self.max_ms, 2),
            "last_ms": round(self.last_ms, 2),
            "p50_60s": p50,
            "p95_60s": p95,
            "p99_60s": p99,
            "samples_60s": len(recent),
        }


class PipelineInspector:
    def __init__(self):
        self._cameras: dict[str, dict[str, _StageStat]] = {}
        self._meta: dict[str, dict] = {}
        self._started_at = time.time()

    def record(self, camera_id: str, stage: str, ms: float,
               error: bool = False, timeout: bool = False) -> None:
        stat = self._cameras.setdefault(camera_id, {}).setdefault(stage, _StageStat())
        stat.record(ms, error=error, timeout=timeout)

    def set_meta(self, camera_id: str, **kw) -> None:
        self._meta.setdefault(camera_id, {}).update(kw)

    def fps(self, camera_id: str) -> float:
        """FPS pipeline effectif = frames décodées sur les 30 dernières secondes."""
        stages = self._cameras.get(camera_id, {})
        stat = stages.get("decode") or stages.get("fetch")
        if not stat:
            return 0.0
        cutoff = time.time() - 30
        n = sum(1 for ts, _ in stat.window if ts >= cutoff)
        return round(n / 30.0, 2)

    def camera_snapshot(self, camera_id: str) -> dict:
        stages = self._cameras.get(camera_id, {})
        ordered = {s: stages[s].to_dict() for s in STAGE_ORDER if s in stages}
        for s, stat in stages.items():
            if s not in ordered:
                ordered[s] = stat.to_dict()
        return {
            "stages": ordered,
            "fps": self.fps(camera_id),
            "meta": dict(self._meta.get(camera_id, {})),
        }

    def system(self) -> dict:
        out: dict = {"uptime_s": round(time.time() - self._started_at, 1)}
        try:
            import psutil
            proc = psutil.Process()
            out["cpu_percent"] = psutil.cpu_percent(interval=None)
            out["process_cpu_percent"] = proc.cpu_percent(interval=None)
            vm = psutil.virtual_memory()
            out["ram"] = {
                "total_mb": round(vm.total / 1048576),
                "used_mb": round(vm.used / 1048576),
                "percent": vm.percent,
                "process_rss_mb": round(proc.memory_info().rss / 1048576, 1),
            }
        except Exception as e:
            out["psutil_error"] = str(e)[:100]
        try:
            import torch
            if torch.cuda.is_available():
                out["gpu"] = {
                    "device": torch.cuda.get_device_name(0),
                    "vram_allocated_mb": round(torch.cuda.memory_allocated(0) / 1048576, 1),
                    "vram_reserved_mb": round(torch.cuda.memory_reserved(0) / 1048576, 1),
                    "vram_total_mb": round(
                        torch.cuda.get_device_properties(0).total_memory / 1048576),
                }
            else:
                out["gpu"] = {"available": False}
        except Exception:
            out["gpu"] = {"available": False}
        return out

    def snapshot(self) -> dict:
        return {
            "cameras": {cid: self.camera_snapshot(cid) for cid in self._cameras},
            "system": self.system(),
            "stage_order": STAGE_ORDER,
        }

    def reset(self, camera_id: Optional[str] = None) -> None:
        if camera_id:
            self._cameras.pop(camera_id, None)
            self._meta.pop(camera_id, None)
        else:
            self._cameras.clear()
            self._meta.clear()


inspector = PipelineInspector()
