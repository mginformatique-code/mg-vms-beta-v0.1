"""Tests video-pipeline-v2 · 3 pipelines indépendants (direct_rtsp / mjpeg / mediamtx).

Couvre les scénarios obligatoires du chantier (exécutables sans caméra physique,
les sources RTSP réelles étant simulées par les mires locales go2rtc) :
  1. caméra RTSP valide            → probe direct_rtsp online
  2. caméra RTSP invalide          → erreur explicite (pas de "Unknown error")
  4. caméra inaccessible           → offline + raison TCP
  5. reconnexion après coupure     → broker MJPEG relance ffmpeg et re-produit
  6. pipeline MJPEG                → frames réelles + FPS + statut online
  7. pipeline MediaMTX             → path ready + statut online
  8. MediaMTX WebRTC (WHEP)        → SDP answer valide
  9. plusieurs viewers             → 1 seul ffmpeg partagé, 2 consommateurs servis
 10. changement de pipeline        → path MediaMTX créé puis purgé proprement
 11. caméra offline / 12. retour online → quick_probe pipeline-aware
 + AUCUN pipeline ne dépend de Go2RTC (garantie structurelle).

Le scénario 3 (mauvais mot de passe RTSP → 401) nécessite une caméra réelle
authentifiée : il fait partie de la checklist LAN (192.168.1.51).
"""
import asyncio
import os
import socket
import sys
import time
import uuid

import pytest

DEMO_RTSP = "rtsp://127.0.0.1:8554/cam_demo-cam-001"   # mire locale go2rtc (source RTSP réelle)


def _fresh_motor_client():
    import motor.motor_asyncio
    client = motor.motor_asyncio.AsyncIOMotorClient(os.environ["MONGO_URL"])
    new_db = client[os.environ["DB_NAME"]]
    for mod_name in ("database", "auth", "streaming", "routers"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "db"):
            mod.db = new_db
    return new_db


def _cam(pipeline: str, rtsp_url: str = DEMO_RTSP) -> dict:
    return {"id": f"test-v2-{pipeline}-{uuid.uuid4().hex[:6]}", "name": f"pytest {pipeline}",
            "rtsp_url": rtsp_url, "stream_pipeline": pipeline}


# ── 1. RTSP valide → direct_rtsp online (probe réel DESCRIBE) ────────────────
def test_direct_rtsp_valid_source_online():
    async def run():
        _fresh_motor_client()
        from video_pipelines import direct_rtsp as p
        st = await p.get_status(_cam("direct_rtsp"))
        assert st["pipeline"] == "direct_rtsp"
        assert st["status"] == "online", st
        assert st["codec"] == "h264"
        assert st["browser_playable"] is False
    asyncio.run(run())


# ── 2. RTSP invalide (chemin inexistant) → erreur EXPLICITE ──────────────────
def test_direct_rtsp_invalid_path_explicit_error():
    async def run():
        _fresh_motor_client()
        from video_pipelines import direct_rtsp as p
        st = await p.get_status(_cam("direct_rtsp", "rtsp://127.0.0.1:8554/nexiste_pas"))
        assert st["status"] == "offline"
        assert st["error"], "l'erreur doit être renseignée"
        assert "unknown" not in st["error"].lower()
    asyncio.run(run())


# ── 4/11. caméra inaccessible → offline avec raison TCP ──────────────────────
def test_unreachable_camera_offline_with_reason():
    async def run():
        _fresh_motor_client()
        from video_pipelines.status import quick_probe
        s = socket.socket(); s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]; s.close()
        for pipeline in ("direct_rtsp", "mjpeg"):
            status, err = await quick_probe(_cam(pipeline, f"rtsp://127.0.0.1:{port}/x"))
            assert status == "offline", pipeline
            assert "injoignable" in err
    asyncio.run(run())


# ── 12. caméra qui revient online (port TCP à nouveau ouvert) ────────────────
def test_camera_back_online():
    async def run():
        _fresh_motor_client()
        from video_pipelines.status import quick_probe
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        port = srv.getsockname()[1]
        try:
            status, err = await quick_probe(_cam("direct_rtsp", f"rtsp://127.0.0.1:{port}/x"))
            assert status == "online", err
        finally:
            srv.close()
    asyncio.run(run())


# ── 6. pipeline MJPEG : frames réelles, FPS, statut ──────────────────────────
def test_mjpeg_broker_produces_frames():
    async def run():
        from video_pipelines import mjpeg as p
        cam_id = f"test-v2-broker-{uuid.uuid4().hex[:6]}"
        b = p.ensure_broker(cam_id, DEMO_RTSP)
        try:
            assert await p.wait_first_frame(b, timeout=15), b.last_error
            assert b.latest[:3] == b"\xff\xd8\xff"
            await asyncio.sleep(2.5)
            st = p.get_status(cam_id)
            assert st["state"] == "online"
            assert st["fps"] > 0
            assert st["last_frame_at"] is not None
        finally:
            p.stop_broker(cam_id)
    asyncio.run(run())


# ── 9. plusieurs viewers : 1 SEUL ffmpeg partagé, fraîcheur pour chacun ──────
def test_mjpeg_multiple_viewers_share_one_ffmpeg():
    async def run():
        from video_pipelines import mjpeg as p
        cam_id = f"test-v2-multi-{uuid.uuid4().hex[:6]}"
        b = p.ensure_broker(cam_id, DEMO_RTSP)
        try:
            assert await p.wait_first_frame(b, timeout=15), b.last_error
            b2 = p.ensure_broker(cam_id, DEMO_RTSP)
            assert b2 is b, "le broker doit être PARTAGÉ (1 ffmpeg par caméra)"

            async def consume(n):
                out = []
                async for chunk in p.multipart_generator(b):
                    out.append(chunk)
                    if len(out) >= n:
                        break
                return out
            r1, r2 = await asyncio.wait_for(asyncio.gather(consume(3), consume(3)), timeout=20)
            assert len(r1) == 3 and len(r2) == 3
            assert all(b"image/jpeg" in c for c in r1 + r2)
        finally:
            p.stop_broker(cam_id)
    asyncio.run(run())


# ── 5. reconnexion après coupure : ffmpeg tué → frames de nouveau produites ──
def test_mjpeg_reconnect_after_kill():
    async def run():
        from video_pipelines import mjpeg as p
        cam_id = f"test-v2-reco-{uuid.uuid4().hex[:6]}"
        b = p.ensure_broker(cam_id, DEMO_RTSP)
        try:
            assert await p.wait_first_frame(b, timeout=15), b.last_error
            seq_before = b.seq
            b.proc.kill()                      # simulate coupure réseau/processus
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if b.seq > seq_before and time.monotonic() - b.last_frame_ts < 3:
                    break
                await asyncio.sleep(0.3)
            assert b.seq > seq_before, "le watchdog doit relancer ffmpeg et re-produire des frames"
            assert b.restarts >= 2
        finally:
            p.stop_broker(cam_id)
    asyncio.run(run())


# ── 7. pipeline MediaMTX : path dynamique + statut online ────────────────────
def test_mediamtx_path_and_status():
    async def run():
        from video_pipelines import mediamtx as p
        cam = _cam("mediamtx")
        try:
            assert await p.ensure_path(cam) is True
            state = None
            for _ in range(20):
                state = await p.get_path_state(cam["id"])
                if state and state.get("ready"):
                    break
                await asyncio.sleep(0.5)
            assert state and state.get("ready"), state
            st = await p.get_status(cam)
            assert st["pipeline"] == "mediamtx"
            assert st["status"] == "online", st
            assert st["codec"] == "h264"
        finally:
            await p.remove_path(cam["id"])
    asyncio.run(run())


# ── 8. MediaMTX WebRTC : négociation WHEP officielle ─────────────────────────
def test_mediamtx_whep_exchange():
    async def run():
        from video_pipelines import mediamtx as p
        cam = _cam("mediamtx")
        offer = ("v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"
                 "m=video 9 UDP/TLS/RTP/SAVPF 96\r\nc=IN IP4 0.0.0.0\r\n"
                 "a=ice-ufrag:pytest\r\na=ice-pwd:pytestpytestpytestpytest\r\n"
                 "a=fingerprint:sha-256 " + ":".join(["00"] * 32) + "\r\n"
                 "a=setup:actpass\r\na=mid:0\r\na=recvonly\r\na=rtpmap:96 H264/90000\r\n")
        try:
            assert await p.ensure_path(cam) is True
            for _ in range(20):
                state = await p.get_path_state(cam["id"])
                if state and state.get("ready"):
                    break
                await asyncio.sleep(0.5)
            answer, session = await p.whep_exchange(cam["id"], offer)
            assert answer.startswith("v=0"), answer[:80]
            assert session, "la session WHEP doit être retournée (Location)"
            await p.whep_close(session)
        finally:
            await p.remove_path(cam["id"])
    asyncio.run(run())


# ── 10. changement de pipeline : purge propre du path MediaMTX ───────────────
def test_pipeline_switch_removes_mediamtx_path():
    async def run():
        from video_pipelines import mediamtx as p
        cam = _cam("mediamtx")
        assert await p.ensure_path(cam) is True
        await p.remove_path(cam["id"])          # bascule mediamtx → mjpeg/direct
        assert await p.get_path_state(cam["id"]) is None
    asyncio.run(run())


# ── Statut pipeline-aware : jamais Go2RTC ────────────────────────────────────
def test_quick_probe_never_uses_go2rtc(monkeypatch):
    async def run():
        _fresh_motor_client()
        import streaming
        from video_pipelines.status import quick_probe

        async def _forbidden(*a, **k):
            raise AssertionError("Go2RTC interdit dans le statut v2")
        monkeypatch.setattr(streaming, "_get_go2rtc_stream_sources", _forbidden)
        monkeypatch.setattr(streaming, "_stream_bytes_recv", _forbidden)
        status, _ = await quick_probe(_cam("direct_rtsp"))
        assert status == "online"
    asyncio.run(run())


# ── Garanties structurelles : zéro dépendance Go2RTC dans video_pipelines ────
def test_video_pipelines_source_has_zero_go2rtc_dependency():
    base = "/app/backend/video_pipelines"
    for fn in ("base.py", "mjpeg.py", "mediamtx.py", "direct_rtsp.py", "status.py"):
        src = open(f"{base}/{fn}").read().lower()
        for forbidden in ("_ensure_variants", "cam_xxx", "go2rtc_url", "1984"):
            assert forbidden not in src, f"{fn} contient une dépendance Go2RTC : {forbidden}"
    # Seule exception documentée : le relais RTSP des caméras DÉMO (mires locales)
    src = open(f"{base}/base.py").read()
    assert "GO2RTC_RTSP" in src and "demo" in src


# ── Contrat video-status : format UNIQUE pour les 3 pipelines ────────────────
def test_video_status_contract_unified():
    async def run():
        _fresh_motor_client()
        from video_pipelines.status import get_video_status
        keys = {"camera_id", "pipeline", "status", "source", "codec", "fps",
                "last_frame_at", "latency_ms", "error", "checked_at"}
        for pipeline in ("direct_rtsp", "mjpeg"):
            st = await get_video_status(_cam(pipeline))
            assert keys.issubset(st.keys()), f"{pipeline}: {sorted(st.keys())}"
    asyncio.run(run())
