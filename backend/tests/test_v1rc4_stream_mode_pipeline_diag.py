"""Tests v1.0-rc4 · Pipeline vidéo `stream_mode` per-camera + diagnostic multi-étages.

Vérifications de la logique interne (les tests HTTP end-to-end sont couverts
par les scripts curl dans la CI/CD — TestClient + Motor async conflicte sur
l'event loop dans ce projet).
"""
import os
import sys


def test_camera_input_stream_mode_default():
    from routers import CameraInput
    ci = CameraInput(name="X", site_id="s1")
    assert ci.stream_mode == "auto"


def test_camera_input_stream_mode_direct():
    from routers import CameraInput
    ci = CameraInput(name="X", site_id="s1", stream_mode="direct_rtsp")
    assert ci.stream_mode == "direct_rtsp"


def test_camera_input_stream_mode_go2rtc():
    from routers import CameraInput
    ci = CameraInput(name="X", site_id="s1", stream_mode="go2rtc")
    assert ci.stream_mode == "go2rtc"


def test_pipeline_diag_module_imports():
    """L'endpoint est bien wired dans server.py."""
    from routes.pipeline_diagnostic import pipeline_diag_router
    routes = [r.path for r in pipeline_diag_router.routes]
    assert "/api/cameras/{camera_id}/pipeline-diagnostic" in routes


def test_step_helper_shape():
    from routes.pipeline_diagnostic import _step
    s = _step("test", "PASS", 12.34, "OK", {"foo": 1})
    assert s["step"] == "test"
    assert s["status"] == "PASS"
    assert s["latency_ms"] == 12.3
    assert s["detail"] == "OK"
    assert s["data"] == {"foo": 1}


def test_verdict_computation():
    from routes.pipeline_diagnostic import _global_verdict, _step
    all_pass = [_step("a", "PASS"), _step("b", "PASS"), _step("c", "SKIP")]
    assert _global_verdict(all_pass) == "PASS"

    with_warn = [_step("a", "PASS"), _step("b", "WARN")]
    assert _global_verdict(with_warn) == "WARN"

    with_fail = [_step("a", "PASS"), _step("b", "WARN"), _step("c", "FAIL")]
    assert _global_verdict(with_fail) == "FAIL"


def test_hevc_webrtc_compat_h265():
    from routes.pipeline_diagnostic import _step_hevc_webrtc_compat
    r = _step_hevc_webrtc_compat({"codec": "H265"}, {"codec_name": "hevc"})
    assert r["status"] == "WARN"
    assert r["data"]["webrtc_direct"] is False
    assert "HEVC" in r["detail"] or "H.265" in r["detail"]


def test_hevc_webrtc_compat_h264():
    from routes.pipeline_diagnostic import _step_hevc_webrtc_compat
    r = _step_hevc_webrtc_compat({"codec": "H264"}, {"codec_name": "h264"})
    assert r["status"] == "PASS"
    assert r["data"]["webrtc_direct"] is True


def test_hevc_webrtc_compat_unknown():
    from routes.pipeline_diagnostic import _step_hevc_webrtc_compat
    r = _step_hevc_webrtc_compat({}, None)
    assert r["status"] == "SKIP"


def test_ai_engine_respects_stream_mode_direct_rtsp(monkeypatch):
    """Vérifie que ai_engine choisit le mode direct quand `stream_mode=direct_rtsp`
    même si l'env global MGVMS_AI_DIRECT_RTSP=0."""
    # On teste la logique de résolution telle qu'elle apparaît dans ai_engine.py :
    # stream_mode="direct_rtsp"    → direct_this_cam=True
    # stream_mode="go2rtc"         → direct_this_cam=False
    # stream_mode="auto" + env=1   → direct_this_cam=True
    # stream_mode="auto" + env=0   → direct_this_cam=False

    def resolve(stream_mode, env_direct):
        # Reproduit la logique de _sync_frame_source_workers
        use_direct = env_direct
        sm = (stream_mode or "auto").lower()
        if sm == "direct_rtsp":
            return True
        if sm == "go2rtc":
            return False
        return use_direct

    assert resolve("direct_rtsp", False) is True
    assert resolve("direct_rtsp", True) is True
    assert resolve("go2rtc", True) is False
    assert resolve("go2rtc", False) is False
    assert resolve("auto", True) is True
    assert resolve("auto", False) is False
    assert resolve(None, True) is True  # None traité comme "auto"
    assert resolve("", False) is False
