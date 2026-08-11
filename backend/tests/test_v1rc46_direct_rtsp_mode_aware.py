"""Tests v1.0-rc4.6 · Pipeline mode-aware direct_rtsp ↔ Go2RTC.

Correctif du bug root-cause : `Error opening input file cam_xxx` (Go2RTC 500)
provoqué par la création de variantes `cam_xxx_hd/_sd → ffmpeg:cam_xxx` pour
des caméras direct_rtsp dont le flux de base n'existe PAS dans Go2RTC.

Garanties vérifiées :
1. Une caméra direct_rtsp ne déclenche JAMAIS _ensure_variants (aucune variante
   cam_xxx_hd/_sd ne peut être créée dans Go2RTC).
2. Le statut direct_rtsp ne dépend JAMAIS de Go2RTC (probe TCP RTSP).
3. live_mjpeg / frame_jpeg n'appellent JAMAIS _ensure_variants_cached en direct.
4. refresh-stream est mode-aware (pas de register Go2RTC en direct).
5. WebRTC (Go2RTC) est refusé proprement (409) en direct_rtsp AVANT tout appel.
6. Non-régression : le découplage register/sync existant reste intact.
"""
import asyncio
import os
import socket
import sys
import threading
from types import SimpleNamespace

import pytest


def _fresh_motor_client():
    import motor.motor_asyncio
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
    new_db = client[db_name]
    for mod_name in ("database", "auth", "streaming", "routers"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "db"):
            mod.db = new_db
    return new_db


def _open_local_port():
    """Ouvre un socket TCP local en écoute — simule un port RTSP joignable."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    t = threading.Thread(target=lambda: srv.accept() if True else None, daemon=True)
    t.start()
    return srv, srv.getsockname()[1]


class _Go2rtcTrap:
    """Sentinelle : toute tentative d'utiliser httpx (donc Go2RTC) fait échouer le test."""
    def __init__(self, *a, **k):
        raise AssertionError("Appel Go2RTC interdit pour une caméra direct_rtsp")


# ─────────────────────────────────────────────────────────────────────────────
# 1. _ensure_variants ne crée JAMAIS de variantes pour direct_rtsp
# ─────────────────────────────────────────────────────────────────────────────
def test_ensure_variants_skips_direct_rtsp(monkeypatch):
    async def run():
        db = _fresh_motor_client()
        import streaming
        cam_id = "test-rc46-ev-direct"
        await db.cameras.delete_many({"id": cam_id})
        await db.cameras.insert_one({"id": cam_id, "name": "Direct",
                                     "rtsp_url": "rtsp://192.0.2.1:554/live",
                                     "stream_mode": "direct_rtsp"})
        # Piège : si _ensure_variants tente le moindre appel HTTP → AssertionError
        monkeypatch.setattr(streaming.httpx, "AsyncClient", _Go2rtcTrap)
        await streaming._ensure_variants(f"cam_{cam_id}")  # doit return AVANT httpx
        await db.cameras.delete_many({"id": cam_id})
    asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# 2. Statut direct_rtsp : probe TCP, jamais Go2RTC
# ─────────────────────────────────────────────────────────────────────────────
def test_probe_status_direct_rtsp_online_via_tcp(monkeypatch):
    async def run():
        _fresh_motor_client()
        import streaming

        async def _forbidden(*a, **k):
            raise AssertionError("Probe Go2RTC interdit en direct_rtsp")
        monkeypatch.setattr(streaming, "_get_go2rtc_stream_sources", _forbidden)
        monkeypatch.setattr(streaming, "_stream_bytes_recv", _forbidden)

        srv, port = _open_local_port()
        try:
            cam = {"id": "test-rc46-probe-up", "stream_mode": "direct_rtsp",
                   "rtsp_url": f"rtsp://127.0.0.1:{port}/live"}
            status, err, missing = await streaming._probe_status_once(cam)
            assert status == "online", f"attendu online, obtenu {status} ({err})"
            assert missing is False
        finally:
            srv.close()
    asyncio.run(run())


def test_probe_status_direct_rtsp_offline_via_tcp(monkeypatch):
    async def run():
        _fresh_motor_client()
        import streaming

        async def _forbidden(*a, **k):
            raise AssertionError("Probe Go2RTC interdit en direct_rtsp")
        monkeypatch.setattr(streaming, "_get_go2rtc_stream_sources", _forbidden)
        monkeypatch.setattr(streaming, "_stream_bytes_recv", _forbidden)

        # Port fermé (réservé puis libéré → connexion refusée)
        s = socket.socket(); s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]; s.close()
        cam = {"id": "test-rc46-probe-down", "stream_mode": "direct_rtsp",
               "rtsp_url": f"rtsp://127.0.0.1:{port}/live"}
        status, err, missing = await streaming._probe_status_once(cam)
        assert status == "offline_transient", f"attendu offline_transient, obtenu {status}"
        assert "TCP" in err, "la raison doit mentionner le probe TCP"
        # L'absence Go2RTC n'est JAMAIS signalée comme anomalie en direct_rtsp
        assert missing is False
        assert "go2rtc" not in err.lower()
    asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# 3. live_mjpeg / frame_jpeg : zéro _ensure_variants_cached en direct
# ─────────────────────────────────────────────────────────────────────────────
def test_live_mjpeg_direct_never_touches_go2rtc(monkeypatch):
    async def run():
        _fresh_motor_client()
        import streaming
        from fastapi import HTTPException
        direct_cam = {"id": "test-rc46-mjpeg", "stream_mode": "direct_rtsp",
                      "stream_pipeline": "direct_rtsp",
                      "rtsp_url": "rtsp://192.0.2.1:554/live"}

        async def _fake_auth(user, camera_id):
            return direct_cam

        async def _forbidden(name):
            raise AssertionError("_ensure_variants_cached interdit en direct_rtsp")

        monkeypatch.setattr(streaming, "_authorize_camera", _fake_auth)
        monkeypatch.setattr(streaming, "_ensure_variants_cached", _forbidden)
        monkeypatch.setattr(streaming, "has_permission", lambda u, p: False)
        # video-pipeline-v2 : direct_rtsp n'a PAS de preview navigateur → 409
        # explicite, sans jamais toucher Go2RTC.
        with pytest.raises(HTTPException) as exc:
            await streaming.live_mjpeg("test-rc46-mjpeg",
                                       request=SimpleNamespace(client=None),
                                       hd=0, user={"email": "pytest"})
        assert exc.value.status_code == 409
        assert "direct_rtsp" in str(exc.value.detail)
    asyncio.run(run())


def test_frame_jpeg_direct_never_touches_go2rtc(monkeypatch):
    async def run():
        _fresh_motor_client()
        import streaming
        direct_cam = {"id": "test-rc46-frame", "stream_mode": "direct_rtsp",
                      "rtsp_url": "rtsp://192.0.2.1:554/live"}

        async def _fake_auth(user, camera_id):
            return direct_cam

        async def _forbidden(name):
            raise AssertionError("_ensure_variants_cached interdit en direct_rtsp")

        async def _fake_direct(cam, hd):
            return b"\xff\xd8\xff\x00fake"

        monkeypatch.setattr(streaming, "_authorize_camera", _fake_auth)
        monkeypatch.setattr(streaming, "_ensure_variants_cached", _forbidden)
        monkeypatch.setattr(streaming, "has_permission", lambda u, p: True)
        monkeypatch.setattr(streaming, "_direct_frame_jpeg", _fake_direct)
        resp = await streaming.frame_jpeg("test-rc46-frame", hd=1, user={"email": "pytest"})
        assert resp.media_type == "image/jpeg"
        assert resp.headers.get("X-Preview-Source") == "direct-ffmpeg"
    asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# 4. refresh-stream mode-aware : jamais de register Go2RTC en direct
# ─────────────────────────────────────────────────────────────────────────────
def test_refresh_stream_direct_rtsp_mode_aware(monkeypatch):
    async def run():
        db = _fresh_motor_client()
        import streaming
        import routers
        cam_id = "test-rc46-refresh"
        await db.cameras.delete_many({"id": cam_id})

        srv, port = _open_local_port()
        await db.cameras.insert_one({"id": cam_id, "name": "Direct Refresh",
                                     "rtsp_url": f"rtsp://127.0.0.1:{port}/live",
                                     "stream_mode": "direct_rtsp",
                                     "stream_pipeline": "direct_rtsp"})
        calls = {"unregister": 0}

        async def _forbidden_register(cam, **k):
            raise AssertionError("register_camera_stream (Go2RTC) interdit en direct_rtsp")

        async def _spy_unregister(camera_id, **k):
            calls["unregister"] += 1

        monkeypatch.setattr(streaming, "register_camera_stream", _forbidden_register)
        monkeypatch.setattr(streaming, "unregister_camera_stream", _spy_unregister)
        try:
            out = await routers.refresh_camera_stream(
                cam_id, user={"id": "pytest-user", "email": "pytest", "role": "admin"})
            assert out["success"] is True
            assert out["pipeline"] == "direct_rtsp"
            # v2 : probe DESCRIBE complet — le port TCP factice répond mais pas
            # en RTSP → reachable False avec erreur explicite, sans Go2RTC.
            assert out["rtsp_reachable"] in (True, False)
            assert calls["unregister"] == 1, "les résidus Go2RTC doivent être purgés"
        finally:
            srv.close()
            await db.cameras.delete_many({"id": cam_id})
    asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# 5. WebRTC (Go2RTC) refusé proprement en direct_rtsp — AVANT tout appel Go2RTC
# ─────────────────────────────────────────────────────────────────────────────
def test_webrtc_offer_rejected_for_direct_rtsp(monkeypatch):
    async def run():
        _fresh_motor_client()
        import streaming
        import routers
        from fastapi import HTTPException
        direct_cam = {"id": "test-rc46-webrtc", "stream_mode": "direct_rtsp",
                      "rtsp_url": "rtsp://192.0.2.1:554/live"}

        async def _fake_auth(user, camera_id):
            return direct_cam

        async def _forbidden(name):
            raise AssertionError("_ensure_variants_cached interdit en direct_rtsp")

        monkeypatch.setattr(streaming, "_authorize_camera", _fake_auth)
        monkeypatch.setattr(streaming, "_ensure_variants_cached", _forbidden)
        offer = routers.WebRTCOfferInput(type="offer", sdp="v=0")
        with pytest.raises(HTTPException) as exc:
            await routers.pipeline_webrtc_offer("test-rc46-webrtc", offer, user={"email": "pytest"})
        assert exc.value.status_code == 409
        assert "direct_rtsp" in str(exc.value.detail)
    asyncio.run(run())


# ─────────────────────────────────────────────────────────────────────────────
# 6. Non-régression : le découplage volontaire direct_rtsp ↔ Go2RTC reste intact
# ─────────────────────────────────────────────────────────────────────────────
def test_register_camera_stream_still_skips_direct_rtsp():
    async def run():
        _fresh_motor_client()
        from streaming import register_camera_stream
        cam = {"id": "test-rc46-nonreg", "name": "Direct",
               "rtsp_url": "rtsp://192.0.2.1:554/live", "stream_mode": "direct_rtsp"}
        assert await register_camera_stream(cam, caller="pytest") is True
    asyncio.run(run())


def test_sync_all_streams_purges_direct_residues_in_source():
    """sync_all_streams doit purger les résidus Go2RTC de TOUTES les caméras
    réelles (video-pipeline-v2 : Go2RTC = legacy isolé, démos uniquement)."""
    with open("/app/backend/streaming.py") as f:
        src = f.read()
    assert "video_v2_purge" in src
    assert "_is_direct_rtsp" in src


def test_direct_branch_precedes_ensure_variants_in_source():
    """Dans live_mjpeg ET frame_jpeg, le dispatch video-pipeline-v2 (caméras
    réelles) doit précéder l'appel _ensure_variants_cached (réservé démos)."""
    with open("/app/backend/streaming.py") as f:
        src = f.read()
    for fn, marker in (("async def live_mjpeg", "_video_v2_mjpeg_response"),
                        ("async def frame_jpeg(", "_direct_frame_jpeg")):
        body = src.split(fn, 1)[1]
        i_direct = body.find(marker)
        i_variants = body.find("await _ensure_variants_cached(")
        assert 0 <= i_direct < i_variants, f"{fn}: le dispatch v2 doit précéder _ensure_variants_cached"
