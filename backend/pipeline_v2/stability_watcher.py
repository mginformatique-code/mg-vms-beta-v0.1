"""Pipeline v2 · Stability Watcher — snapshot minute-par-minute des métriques.

Mandat v0.8-rc7 (FEATURE FREEZE · Sprint 4 · Priorité #4) :

    Toutes les 60 s, capturer l'état complet du système et le conserver
    dans un ring buffer 72 h. Permet de calculer p50/p95/p99 sur toute
    fenêtre glissante (1 h / 24 h / 72 h).

Ring buffer 72 h × 60 min = 4320 snapshots max ≈ 4 MB RAM.

Métriques capturées :
    Backend   : RAM %, CPU %, RSS process, threads count, asyncio tasks
    Pipeline  : par-caméra { fps, p95, p99, dropped }
    Mongo     : ping OK, active_connections
    go2rtc    : streams count, error count depuis boot

Aucune écriture disque — tout est en RAM circulaire (perdu au restart,
c'est OK, c'est un watcher runtime pas un audit persistant).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("pipeline_v2.stability_watcher")


# ─── Config ─────────────────────────────────────────────────────────
TICK_SECONDS = 60                # snapshot toutes les minutes
MAX_SNAPSHOTS = 60 * 24 * 3       # 72 h × 60 min
WINDOWS = {
    "1h":  60,
    "6h":  60 * 6,
    "24h": 60 * 24,
    "72h": 60 * 24 * 3,
}


@dataclass
class Snapshot:
    """Un cliché système à un instant t."""
    ts: float
    backend: dict = field(default_factory=dict)
    pipeline: dict = field(default_factory=dict)
    mongo: dict = field(default_factory=dict)
    go2rtc: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "backend": self.backend,
            "pipeline": self.pipeline,
            "mongo": self.mongo,
            "go2rtc": self.go2rtc,
        }


class StabilityWatcher:
    def __init__(self):
        self._snapshots: deque[Snapshot] = deque(maxlen=MAX_SNAPSHOTS)
        self._task: Optional[asyncio.Task] = None
        self._started_at: float = 0.0
        self._lock = threading.Lock()

    # ─── Cycle de vie ──────────────────────────────────────────────
    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._started_at = time.time()
        try:
            loop = asyncio.get_event_loop()
            self._task = loop.create_task(self._loop())
            logger.info("stability_watcher : démarrage (tick %ds, max %d snapshots)",
                        TICK_SECONDS, MAX_SNAPSHOTS)
        except RuntimeError:
            logger.warning("stability_watcher : pas d'event loop → skip")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None

    # ─── Boucle principale ─────────────────────────────────────────
    async def _loop(self) -> None:
        # 1er tick immédiat pour ne pas avoir un buffer vide 60 s
        try:
            await self._collect_one()
        except Exception:
            logger.exception("stability_watcher: 1er tick failed")
        while True:
            try:
                await asyncio.sleep(TICK_SECONDS)
                await self._collect_one()
            except asyncio.CancelledError:
                logger.info("stability_watcher : arrêt propre")
                break
            except Exception:
                logger.exception("stability_watcher: tick failed (non bloquant)")

    async def _collect_one(self) -> None:
        snap = Snapshot(ts=time.time())
        snap.backend = _collect_backend()
        snap.pipeline = _collect_pipeline()
        snap.mongo = await _collect_mongo()
        snap.go2rtc = await _collect_go2rtc()
        with self._lock:
            self._snapshots.append(snap)

    # ─── Requêtes ──────────────────────────────────────────────────
    def _list_window(self, window: str) -> list[Snapshot]:
        n = WINDOWS.get(window)
        if n is None:
            return []
        with self._lock:
            arr = list(self._snapshots)
        return arr[-n:] if n < len(arr) else arr

    def snapshot(self, window: str = "1h") -> dict:
        """Retourne les snapshots bruts + agrégats percentiles sur la fenêtre.

        window ∈ {"1h", "6h", "24h", "72h"}
        """
        arr = self._list_window(window)
        return {
            "window": window,
            "snapshot_count": len(arr),
            "tick_seconds": TICK_SECONDS,
            "watcher_uptime_s": round(time.time() - self._started_at, 0)
                if self._started_at else 0,
            "latest": arr[-1].to_dict() if arr else None,
            "aggregates": _aggregate(arr),
        }

    def latest(self) -> Optional[dict]:
        with self._lock:
            if not self._snapshots:
                return None
            return self._snapshots[-1].to_dict()

    def clear(self) -> int:
        with self._lock:
            n = len(self._snapshots)
            self._snapshots.clear()
        return n

    def dump_all(self) -> list[dict]:
        """Utilisé par les tests + rapports export."""
        with self._lock:
            return [s.to_dict() for s in self._snapshots]


# ═════════════════════════════════════════════════════════════════════
# Collecteurs individuels — chacun tolère l'échec en silence
# ═════════════════════════════════════════════════════════════════════
def _collect_backend() -> dict:
    out: dict = {}
    try:
        import psutil
        proc = psutil.Process()
        out["cpu_percent"] = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        out["ram_percent"] = vm.percent
        out["ram_used_mb"] = round(vm.used / 1048576)
        out["process_rss_mb"] = round(proc.memory_info().rss / 1048576, 1)
        out["threads"] = proc.num_threads()
        out["open_files"] = len(proc.open_files() or [])
    except Exception as e:
        out["error"] = str(e)[:80]
    try:
        # asyncio tasks (approx)
        out["asyncio_tasks"] = len(asyncio.all_tasks())
    except RuntimeError:
        out["asyncio_tasks"] = 0
    return out


def _collect_pipeline() -> dict:
    """Snapshot par-caméra des métriques inspector."""
    try:
        from pipeline_v2.inspector import inspector
        cams: dict = {}
        for cid, stages in inspector._cameras.items():
            stage_summary: dict = {}
            for stage_name, stat in stages.items():
                d = stat.to_dict()
                stage_summary[stage_name] = {
                    "calls": d["calls"],
                    "avg_ms_60s": d["avg_ms_60s"],
                    "p95_60s": d["p95_60s"],
                    "p99_60s": d["p99_60s"],
                    "errors": d["errors"],
                }
            cams[cid] = {
                "fps": inspector.fps(cid),
                "stages": stage_summary,
            }
        return {"cameras": cams, "camera_count": len(cams)}
    except Exception as e:
        return {"error": str(e)[:80]}


async def _collect_mongo() -> dict:
    out: dict = {}
    try:
        from database import db
        t0 = time.monotonic()
        await db.command("ping")
        out["ping_ms"] = round((time.monotonic() - t0) * 1000, 2)
        out["ok"] = True
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)[:80]
    return out


async def _collect_go2rtc() -> dict:
    out: dict = {}
    try:
        import httpx
        import os
        base = os.environ.get("GO2RTC_URL", "http://localhost:1984")
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(f"{base}/api/streams")
        if r.status_code == 200:
            data = r.json() or {}
            out["ok"] = True
            out["streams_count"] = len(data)
        else:
            out["ok"] = False
            out["http_status"] = r.status_code
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)[:80]
    return out


def _aggregate(snaps: list[Snapshot]) -> dict:
    """Percentiles p50/p95/p99 sur les principaux compteurs de la fenêtre."""
    if not snaps:
        return {}
    ram = [s.backend.get("ram_percent") for s in snaps if s.backend.get("ram_percent") is not None]
    cpu = [s.backend.get("cpu_percent") for s in snaps if s.backend.get("cpu_percent") is not None]
    rss = [s.backend.get("process_rss_mb") for s in snaps if s.backend.get("process_rss_mb") is not None]
    mongo_ok = sum(1 for s in snaps if s.mongo.get("ok"))
    go_ok = sum(1 for s in snaps if s.go2rtc.get("ok"))
    return {
        "ram_percent":   _percentiles(ram),
        "cpu_percent":   _percentiles(cpu),
        "process_rss_mb": _percentiles(rss),
        "mongo_uptime_pct": round(100 * mongo_ok / len(snaps), 1),
        "go2rtc_uptime_pct": round(100 * go_ok / len(snaps), 1),
    }


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    s = sorted(values)
    def _pct(p: float) -> float:
        k = max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))
        return round(s[k], 2)
    return {
        "count": len(s),
        "min": s[0],
        "max": s[-1],
        "avg": round(sum(s) / len(s), 2),
        "p50": _pct(0.50),
        "p95": _pct(0.95),
        "p99": _pct(0.99),
    }


# ═════════════════════════════════════════════════════════════════════
# Instance globale
# ═════════════════════════════════════════════════════════════════════
watcher = StabilityWatcher()
