"""Pipeline v2 · Trace End-to-End — suit UNE détection à travers tout le pipeline.

Mandat v0.8-rc6 (FEATURE FREEZE · Stabilisation Sprint 3 · Priorité #7) :

    Suivre UNE détection du début à la fin avec les temps exacts.

    Frame → Decode → Motion → Détection → Tracking → Crop → Quality Score
        → OCR 1 → OCR 2 → OCR 3 → Fusion → Mongo → WebSocket → Frontend

Approche :
    * Sampling léger : 1 trace toutes les N frames (défaut N=100) — coût
      quasi-nul en régime nominal.
    * Ring buffer 50 traces max — pas de fuite mémoire.
    * Zéro instrumentation intrusive : context manager `with trace.stage("yolo"): ...`
      dans le code existant.

Ce module est PUR : aucune écriture DB. Le résultat est consulté via
un endpoint diagnostic (`/api/diagnostics/traces`).
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("pipeline_v2.trace")

# ─── Config ─────────────────────────────────────────────────────────
DEFAULT_SAMPLING_N = 100          # 1 trace toutes les N frames
MAX_TRACES = 50                   # taille max du ring buffer
MAX_STAGES_PER_TRACE = 40         # cap sécurité (évite trace corrompue)


@dataclass
class StageEvent:
    """Une étape mesurée dans un trace."""
    name: str
    started_at_ms: float        # relatif au trace.started_at (ms)
    duration_ms: float
    ok: bool = True
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "start_ms": round(self.started_at_ms, 2),
            "duration_ms": round(self.duration_ms, 2),
            "ok": self.ok,
            "detail": self.detail,
        }


@dataclass
class Trace:
    """Un trace end-to-end d'une détection unique."""
    trace_id: str
    camera_id: str
    started_at: float           # epoch (s)
    stages: list[StageEvent] = field(default_factory=list)
    finished: bool = False
    finished_at: float = 0.0
    outcome: dict = field(default_factory=dict)  # ex: {"plates": ["AB123"], "confidence": 0.9}

    @property
    def total_duration_ms(self) -> float:
        if self.finished_at:
            return round((self.finished_at - self.started_at) * 1000, 2)
        return 0.0

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "camera_id": self.camera_id,
            "started_at": self.started_at,
            "stages": [s.to_dict() for s in self.stages],
            "finished": self.finished,
            "total_duration_ms": self.total_duration_ms,
            "outcome": self.outcome,
        }


class TraceCollector:
    """Ring buffer thread-safe des N derniers traces + sampling counter."""

    def __init__(self, sampling_n: int = DEFAULT_SAMPLING_N):
        self._traces: deque[Trace] = deque(maxlen=MAX_TRACES)
        self._per_camera_counter: dict[str, int] = {}
        self._sampling_n = max(1, sampling_n)
        self._lock = threading.Lock()

    # ─── Configuration ─────────────────────────────────────────────
    def set_sampling(self, n: int) -> None:
        with self._lock:
            self._sampling_n = max(1, int(n))

    def get_sampling(self) -> int:
        return self._sampling_n

    # ─── Cycle de vie d'un trace ───────────────────────────────────
    def should_sample(self, camera_id: str) -> bool:
        """True quand cette frame doit être tracée."""
        with self._lock:
            n = self._per_camera_counter.get(camera_id, 0) + 1
            self._per_camera_counter[camera_id] = n
            return (n % self._sampling_n) == 0

    def start_trace(self, camera_id: str) -> Trace:
        t = Trace(
            trace_id=uuid.uuid4().hex[:12],
            camera_id=camera_id,
            started_at=time.time(),
        )
        with self._lock:
            self._traces.append(t)
        return t

    def record_stage(self, trace: Optional[Trace], name: str,
                     duration_ms: float, ok: bool = True, detail: str = "") -> None:
        """Ajoute une étape à un trace (no-op si trace=None)."""
        if trace is None or trace.finished:
            return
        if len(trace.stages) >= MAX_STAGES_PER_TRACE:
            return
        start_ms = (time.time() - trace.started_at) * 1000 - duration_ms
        trace.stages.append(StageEvent(
            name=name, started_at_ms=start_ms,
            duration_ms=duration_ms, ok=ok, detail=detail,
        ))

    def finish_trace(self, trace: Optional[Trace], outcome: Optional[dict] = None) -> None:
        if trace is None or trace.finished:
            return
        trace.finished = True
        trace.finished_at = time.time()
        if outcome:
            trace.outcome.update(outcome)

    # ─── Requêtes ──────────────────────────────────────────────────
    def list_recent(self, camera_id: Optional[str] = None,
                    limit: int = 50) -> list[dict]:
        with self._lock:
            arr = list(self._traces)
        arr.reverse()   # + récents en tête
        if camera_id:
            arr = [t for t in arr if t.camera_id == camera_id]
        return [t.to_dict() for t in arr[:limit]]

    def get(self, trace_id: str) -> Optional[dict]:
        with self._lock:
            for t in self._traces:
                if t.trace_id == trace_id:
                    return t.to_dict()
        return None

    def clear(self) -> int:
        with self._lock:
            n = len(self._traces)
            self._traces.clear()
            self._per_camera_counter.clear()
        return n


# ─── Instance globale ───────────────────────────────────────────────
collector = TraceCollector()


# ═════════════════════════════════════════════════════════════════════
# Helper context manager pour instrumenter du code existant sans fuite
# ═════════════════════════════════════════════════════════════════════
@contextmanager
def stage(trace: Optional[Trace], name: str):
    """Usage :
        with stage(trace, "yolo"):
            r = _model.predict(frame)
    Enregistre automatiquement duration_ms + ok/failed.
    """
    t0 = time.monotonic()
    ok = True
    detail = ""
    try:
        yield
    except Exception as e:
        ok = False
        detail = f"{type(e).__name__}: {str(e)[:80]}"
        raise
    finally:
        dur = (time.monotonic() - t0) * 1000
        collector.record_stage(trace, name, dur, ok=ok, detail=detail)
