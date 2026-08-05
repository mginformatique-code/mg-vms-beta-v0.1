"""Pipeline v2 · Scheduler multi-caméra.

Coordonne le traitement de N caméras avec :
    - FPS IA cible par caméra (ex : Parking 10 FPS, Entrée 25 FPS, Stock 2 FPS)
    - Priorités (une caméra prioritaire mange une part plus grande du GPU)
    - Décodage vidéo UNE seule fois (partagé via frame_source workers)
    - Backpressure : drop-oldest si downstream ne suit pas
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .engine import PipelineEngine
from .interfaces import Frame


@dataclass
class CameraSchedule:
    """Config par caméra : FPS cible + priorité + config pipeline."""
    camera_id: str
    fps_target: float = 5.0     # frames par seconde vers l'IA
    priority: int = 5           # 1 (low) .. 10 (high)
    enabled: bool = True
    camera_config: dict = field(default_factory=dict)   # enabled_plugins, fusion, …
    _next_deadline: float = 0.0  # timestamp du prochain traitement autorisé


class FrameScheduler:
    """Boucle async unique qui pousse les frames vers PipelineEngine.

    Le scheduler ne DÉCODE PAS lui-même — il consomme un ``frame_source``
    (callable → Frame|None) qui expose des frames déjà décodées en mémoire.
    Zero-copie côté scheduler.
    """

    def __init__(self, engine: PipelineEngine,
                 frame_source: Callable[[str], Optional[Frame]],
                 max_concurrent: int = 4):
        """
        Args:
            engine       : PipelineEngine partagé pour toutes les caméras
            frame_source : callable(camera_id) → Frame | None (source de frames)
            max_concurrent : nb de pipelines exécutés en parallèle
        """
        self.engine = engine
        self.frame_source = frame_source
        self.schedules: dict[str, CameraSchedule] = {}
        self._sem = asyncio.Semaphore(max_concurrent)
        self._frame_id_counter = 0
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Compteurs pour monitoring
        self._stats: dict[str, dict] = {}

    def register(self, sched: CameraSchedule) -> None:
        self.schedules[sched.camera_id] = sched

    def unregister(self, camera_id: str) -> None:
        self.schedules.pop(camera_id, None)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            now = time.time()
            # Tri par priorité (plus haute d'abord) puis par deadline
            due = sorted(
                (s for s in self.schedules.values()
                 if s.enabled and s._next_deadline <= now),
                key=lambda s: (-s.priority, s._next_deadline),
            )
            for sched in due:
                # Programme la prochaine deadline immédiatement (drop-oldest)
                interval = 1.0 / max(0.5, sched.fps_target)
                sched._next_deadline = now + interval

                frame = self.frame_source(sched.camera_id)
                if frame is None:
                    continue
                # Alloue frame_id monotone
                self._frame_id_counter += 1
                frame.frame_id = self._frame_id_counter
                # Fire-and-forget via semaphore (backpressure global)
                asyncio.create_task(self._process_one(sched, frame))
            # Sleep court : le scheduler wake-up ~200 fois/s max
            await asyncio.sleep(0.005)

    async def _process_one(self, sched: CameraSchedule, frame: Frame) -> None:
        acquired = self._sem.locked() and self._sem._value == 0
        if acquired:
            # Semaphore saturé → drop cette frame (préserve le temps réel)
            self._bump(sched.camera_id, "dropped")
            return
        async with self._sem:
            t0 = time.perf_counter()
            try:
                await self.engine.process(frame, sched.camera_config)
                self._bump(sched.camera_id, "processed")
            except Exception:
                self._bump(sched.camera_id, "errors")
            finally:
                elapsed = (time.perf_counter() - t0) * 1000
                self._bump_latency(sched.camera_id, elapsed)

    def _bump(self, camera_id: str, key: str) -> None:
        s = self._stats.setdefault(camera_id, {
            "processed": 0, "dropped": 0, "errors": 0, "total_ms_sum": 0.0,
        })
        s[key] = s.get(key, 0) + 1

    def _bump_latency(self, camera_id: str, ms: float) -> None:
        s = self._stats.setdefault(camera_id, {"total_ms_sum": 0.0, "processed": 0})
        s["total_ms_sum"] = s.get("total_ms_sum", 0.0) + ms

    def stats(self) -> dict:
        out = {}
        for cid, s in self._stats.items():
            n = s.get("processed", 0) or 1
            out[cid] = {
                **s,
                "avg_ms": round(s.get("total_ms_sum", 0) / n, 2),
                "fps_target": self.schedules[cid].fps_target if cid in self.schedules else 0,
                "priority": self.schedules[cid].priority if cid in self.schedules else 0,
            }
        return out
