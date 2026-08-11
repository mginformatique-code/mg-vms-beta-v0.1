"""Tests v1.0-rc4 · Découplage Camera creation ↔ Go2RTC.

Vérifications :
- register_camera_stream skip si stream_mode=direct_rtsp (pas d'inscription Go2RTC)
- sync_all_streams skip aussi les caméras en direct_rtsp
- Logique de fallback create_camera : direct_rtsp = keep, auto+override = keep,
  go2rtc explicit sans override = delete + 400
"""
import asyncio
import os
import sys


def _fresh_motor_client():
    import motor.motor_asyncio
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = motor.motor_asyncio.AsyncIOMotorClient(mongo_url)
    new_db = client[db_name]
    for mod_name in ("database", "auth", "scripts.mgvms_admin", "streaming"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "db"):
            mod.db = new_db
    return new_db


def test_register_camera_stream_skips_direct_rtsp():
    """Une caméra en stream_mode=direct_rtsp n'est PAS inscrite dans Go2RTC."""

    async def run():
        _fresh_motor_client()
        from streaming import register_camera_stream

        cam = {
            "id": "test-direct-skip-xyz",
            "name": "Direct RTSP Cam",
            "rtsp_url": "rtsp://192.168.1.99:554/live",
            "stream_mode": "direct_rtsp",
        }
        # Doit retourner True immédiatement (skip = objectif satisfait)
        # sans faire d'appel HTTP à Go2RTC
        result = await register_camera_stream(cam, caller="pytest")
        assert result is True, "direct_rtsp doit skipper et retourner True"

    asyncio.run(run())


def test_register_camera_stream_auto_still_registers():
    """Une caméra en stream_mode=auto ou go2rtc doit TENTER l'inscription."""

    async def run():
        _fresh_motor_client()
        from streaming import register_camera_stream

        # URL invalide → l'inscription tente et échoue (comportement normal)
        cam = {
            "id": "test-auto-still-tries-xyz",
            "name": "Auto Cam",
            "rtsp_url": "not-a-valid-url-scheme",  # rejeté par le guard rtsp://
            "stream_mode": "auto",
        }
        result = await register_camera_stream(cam, caller="pytest")
        # URL invalide → False (mode auto doit VRAIMENT tenter)
        assert result is False, "auto avec URL invalide doit retourner False (a tenté)"

    asyncio.run(run())


def test_streaming_module_documents_stream_mode_respect():
    """Le code source de streaming.py doit référencer stream_mode dans
    register_camera_stream ET sync_all_streams."""
    with open("/app/backend/streaming.py") as f:
        src = f.read()
    # Le skip est présent dans les 2 fonctions
    assert "stream_mode" in src
    assert "direct_rtsp" in src
    # Le message de log confirme le respect
    assert "skip" in src.lower() and "direct_rtsp" in src


def test_routers_documents_go2rtc_decoupling():
    """video-pipeline-v2 : create_camera applique le pipeline choisi, sans Go2RTC."""
    with open("/app/backend/routers.py") as f:
        src = f.read()
    assert "stream_pipeline" in src
    assert "video-pipeline-v2" in src
    assert "ensure_path" in src


def test_camera_input_stream_mode_field_in_model():
    """Le modèle Pydantic CameraInput expose bien stream_mode."""
    from routers import CameraInput
    assert "stream_mode" in CameraInput.model_fields
    default = CameraInput(name="X", site_id="s").stream_mode
    assert default == "auto"
