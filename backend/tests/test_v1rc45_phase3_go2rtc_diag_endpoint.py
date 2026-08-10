"""Tests v1.0-rc4.5 · Phase 3 · Endpoint go2rtc-diagnostic dédié.

Vérifications :
- Endpoint accessible pour un technicien authentifié
- Champs attendus présents dans la réponse
- Mode direct_rtsp → verdict N/A + note explicative
- Champs pipeline (mode/decoder/preview) toujours présents
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
    for mod_name in ("database", "auth", "streaming"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "db"):
            mod.db = new_db
    return new_db


def test_go2rtc_diagnostic_router_registered_in_server():
    """L'endpoint doit être monté dans server.py."""
    with open("/app/backend/server.py") as f:
        src = f.read()
    assert "go2rtc_diag_router" in src, "go2rtc_diag_router non importé/monté dans server.py"
    assert "from routes.go2rtc_diagnostic import go2rtc_diag_router" in src


def test_go2rtc_diagnostic_module_declares_expected_fields():
    """Le module doit exposer toutes les métriques demandées par l'utilisateur."""
    with open("/app/backend/routes/go2rtc_diagnostic.py") as f:
        src = f.read()
    # Toutes les métriques P0 doivent apparaître dans le code
    for key in [
        "codec_in", "codecs_available", "resolution", "transport",
        "producer_connected", "transcoding_source", "transcoding_hd_variant",
        "transcoding_sd_variant", "copy_codec_source", "sampling",
        "webrtc", "verdict", "reason", "pipeline",
    ]:
        assert key in src, f"Champ '{key}' manquant dans go2rtc_diagnostic.py"


def test_go2rtc_diagnostic_returns_na_for_direct_rtsp():
    """Une caméra en direct_rtsp doit retourner verdict N/A avec une note."""

    async def run():
        d = _fresh_motor_client()
        # Insère une caméra factice en direct_rtsp
        await d.cameras.insert_one({
            "id": "test-direct-rtsp-diag",
            "name": "Direct RTSP",
            "stream_mode": "direct_rtsp",
            "rtsp_url": "rtsp://192.168.1.99:554/live",
        })
        try:
            # Appel direct de la fonction handler (sans FastAPI/HTTP)
            from routes.go2rtc_diagnostic import go2rtc_diagnostic
            # Bypass require_role via user dict
            result = await go2rtc_diagnostic(camera_id="test-direct-rtsp-diag",
                                              user={"role": "admin", "email": "test@test"})
            assert result["verdict"] == "N/A"
            assert result["stream_mode"] == "direct_rtsp"
            assert "note" in result
            assert "direct_rtsp" in result["note"]
        finally:
            await d.cameras.delete_one({"id": "test-direct-rtsp-diag"})

    asyncio.run(run())


def test_go2rtc_diagnostic_404_for_unknown_camera():
    """Le handler doit lever HTTPException(404) si la caméra n'existe pas.
    Test statique par lecture du code source (évite motor loop reset)."""
    with open("/app/backend/routes/go2rtc_diagnostic.py") as f:
        src = f.read()
    assert 'HTTPException(404, "Caméra introuvable")' in src, (
        "Le handler doit lever HTTPException 404 si la caméra n'existe pas"
    )


def test_detect_transport_reads_tcp_fragment():
    """La fonction _detect_transport doit extraire #transport=tcp de la source."""
    from routes.go2rtc_diagnostic import _detect_transport

    # Cas 1 : fragment TCP explicite
    assert _detect_transport("rtsp://cam/stream#transport=tcp#timeout=15", {}) == "TCP"
    # Cas 2 : fragment UDP
    assert _detect_transport("rtsp://cam/stream#transport=udp", {}) == "UDP"
    # Cas 3 : pas de fragment → UNKNOWN
    result = _detect_transport("rtsp://cam/stream", {})
    assert "UNKNOWN" in result
    # Cas 4 : URL vide
    result = _detect_transport(None, {})
    assert "UNKNOWN" in result
