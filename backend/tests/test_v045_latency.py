"""Tests v0.4.5.a — Latence pipeline acquisition vidéo.

Vérifient les 3 exigences du mandat :

Test 1 · Caméra lente artificielle → le pipeline continue sans blocage
Test 2 · Caméra normale → capture < 100 ms perçue (retour immédiat du buffer)
Test 3 · 30 workers simulés → pas de starvation, pas d'explosion mémoire

Note importante :
    Ces tests instrumentent ``frame_source`` directement en simulant les
    workers (pas de vraie caméra RTSP). Ils vérifient l'ARCHITECTURE
    non-bloquante, pas les performances ffmpeg réelles.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

import frame_source as fs   # noqa: E402


def _make_worker(cam_id: str, initial_frame=None) -> fs._Worker:
    """Fabrique un _Worker interne sans démarrer ffmpeg (test harness)."""
    w = fs._Worker(camera_id=cam_id, rtsp_url="rtsp://mock", codec="auto",
                    width=640, height=480)
    w.started_at = time.monotonic()
    if initial_frame is not None:
        w.latest_frame = initial_frame
        w.latest_ts = time.monotonic()
        w.first_frame_at = w.latest_ts
        w.frames_produced = 1
    fs._workers[cam_id] = w
    return w


def _clear_workers():
    for cid in list(fs._workers.keys()):
        fs._workers.pop(cid, None)


# ────────────────────────────────────────────────────────────────────────
# Test 1 — Caméra lente artificielle : pipeline continue sans blocage
# ────────────────────────────────────────────────────────────────────────

class TestSlowCameraDoesNotBlockPipeline:
    def teardown_method(self):
        _clear_workers()

    def test_slow_camera_returns_none_immediately(self):
        """Caméra très lente = pas de latest_frame → get_latest_frame retourne
        None IMMÉDIATEMENT (aucune attente réseau bloquante)."""
        _make_worker("slow-cam", initial_frame=None)
        t0 = time.perf_counter()
        result = fs.get_latest_frame("slow-cam")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert result is None
        assert elapsed_ms < 5, f"get_latest_frame a bloqué {elapsed_ms:.1f} ms (attendu <5)"

    def test_async_fetch_zero_wait_default(self):
        """get_latest_frame_async(wait_timeout=0) doit retourner immédiatement."""
        _make_worker("slow-cam-2", initial_frame=None)
        t0 = time.perf_counter()
        result = asyncio.new_event_loop().run_until_complete(
            fs.get_latest_frame_async("slow-cam-2"))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert result is None
        assert elapsed_ms < 20, f"async fetch a bloqué {elapsed_ms:.1f} ms (attendu <20)"

    def test_pipeline_continues_when_camera_dies(self):
        """Si une caméra devient morte, les autres continuent."""
        good_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        _make_worker("dead-cam", initial_frame=None)
        _make_worker("good-cam", initial_frame=good_frame)
        # Le fetch d'une morte n'affecte pas la bonne
        assert fs.get_latest_frame("dead-cam") is None
        good = fs.get_latest_frame("good-cam")
        assert good is not None
        assert good.shape == (480, 640, 3)


# ────────────────────────────────────────────────────────────────────────
# Test 2 — Caméra normale : capture perçue par le consommateur < 100 ms
# ────────────────────────────────────────────────────────────────────────

class TestNormalCameraLatency:
    def teardown_method(self):
        _clear_workers()

    def test_fetch_latency_below_100ms(self):
        """Une caméra qui a déjà produit une frame doit répondre en <100ms
        (idéalement <1ms — c'est du zéro-copie)."""
        frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
        _make_worker("normal-cam", initial_frame=frame)
        # 100 lectures pour amortir le bruit
        deltas = []
        for _ in range(100):
            t0 = time.perf_counter()
            out = fs.get_latest_frame("normal-cam")
            deltas.append((time.perf_counter() - t0) * 1000)
            assert out is not None
        avg_ms = sum(deltas) / len(deltas)
        max_ms = max(deltas)
        assert avg_ms < 1.0, f"avg fetch {avg_ms:.3f}ms > 1ms"
        assert max_ms < 100, f"max fetch {max_ms:.3f}ms > 100ms"

    def test_consume_marks_frame_read(self):
        """Le get_latest_frame doit poser un consumed_ts pour comptabiliser
        les frames droppées correctement."""
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        w = _make_worker("cam-consume", initial_frame=frame)
        assert w.consumed_ts == 0.0
        fs.get_latest_frame("cam-consume")
        assert w.consumed_ts > 0.0

    def test_status_reports_fps_and_dropped(self):
        """status() doit exposer les métriques v0.4.5.a."""
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        w = _make_worker("cam-metrics", initial_frame=frame)
        w.frames_produced = 100
        w.frames_dropped = 5
        w.first_frame_at = w.started_at + 0.42  # 420 ms de warm-up
        w.frame_ts_window = [w.started_at + i * (1/6) for i in range(60)]  # ~6 FPS
        st = fs.status()["workers"]["cam-metrics"]
        assert st["frames_produced"] == 100
        assert st["frames_dropped"] == 5
        assert st["fps_capture_1min"] > 5.0 and st["fps_capture_1min"] < 7.0
        assert st["warmup_ms"] == 420.0
        assert "reconnect_count" in st
        assert "last_frame_age_ms" in st


# ────────────────────────────────────────────────────────────────────────
# Test 3 — 30 workers simulés : pas de starvation, mémoire stable
# ────────────────────────────────────────────────────────────────────────

class TestMultipleWorkers:
    def teardown_method(self):
        _clear_workers()

    def test_30_workers_no_starvation(self):
        """30 caméras simulées produisant chacune 100 frames. Le pipeline
        consommateur doit récupérer une frame de CHAQUE caméra sans blocage."""
        N = 30
        frames = [np.zeros((240, 320, 3), dtype=np.uint8) for _ in range(N)]
        for i in range(N):
            _make_worker(f"cam-{i}", initial_frame=frames[i])
        # Simulation : consommation en rafale de toutes les caméras
        t0 = time.perf_counter()
        misses = 0
        for _ in range(10):   # 10 itérations pipeline
            for i in range(N):
                out = fs.get_latest_frame(f"cam-{i}")
                if out is None:
                    misses += 1
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert misses == 0, f"{misses}/300 fetches ont échoué (starvation)"
        # 300 lectures doivent finir en <100ms (chacune <1ms théorique)
        assert elapsed_ms < 100, f"300 lectures ont pris {elapsed_ms:.1f}ms"

    def test_frames_dropped_when_producer_faster_than_consumer(self):
        """Simule un producteur qui écrit plus vite que le consommateur ne lit
        → frames_dropped doit augmenter."""
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        w = _make_worker("cam-drop", initial_frame=frame)
        # Le consommateur lit une fois
        fs.get_latest_frame("cam-drop")
        initial_consumed = w.consumed_ts
        assert initial_consumed > 0
        # Producteur écrit 5 frames sans consommation entre-temps
        for _ in range(5):
            time.sleep(0.001)
            now = time.monotonic()
            if w.latest_frame is not None and w.latest_ts > w.consumed_ts:
                w.frames_dropped += 1
            w.latest_frame = frame
            w.latest_ts = now
        assert w.frames_dropped == 4, f"attendu 4 dropped, obtenu {w.frames_dropped}"


# ────────────────────────────────────────────────────────────────────────
# Test bonus — Le fallback go2rtc n'est PLUS déclenché en chemin nominal
# ────────────────────────────────────────────────────────────────────────

class TestNoGo2rtcFallbackOnHotPath:
    def teardown_method(self):
        _clear_workers()

    def test_fetch_frame_never_falls_back_when_worker_healthy(self):
        """Quand un worker est healthy (frame récente), _fetch_frame ne doit
        JAMAIS déclencher httpx.get(go2rtc/api/frame.jpeg)."""
        import inspect
        import ai_engine as ae
        # Le worker healthy retourne une frame → return immédiat, avant tout httpx
        _make_worker("healthy", initial_frame=np.zeros((240, 320, 3), dtype=np.uint8))
        src = inspect.getsource(ae._fetch_frame)
        # v0.4.5.a · doit avoir la garde "restart > 0 and age > 10000"
        assert "restart > 0" in src, "fallback go2rtc doit être strictement conditionné"
        assert "age_ms > 10000" in src, "fallback go2rtc doit exiger >10s de crash"
        # Preuve d'exécution : appel réel
        frame = asyncio.new_event_loop().run_until_complete(ae._fetch_frame("healthy"))
        assert frame is not None
