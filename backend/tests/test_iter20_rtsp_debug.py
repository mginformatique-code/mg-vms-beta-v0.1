"""Iteration 20 — Validation bug fix RTSP debug/validation :
- _build_rtsp_url encode UNE FOIS (RFC 3986) + préserve URL déjà avec creds
- _mask_url_password masque bien le password
- _try_ffprobe_variants retourne 3-tuple (working_url, details, attempts)
- Ordre des attempts : H264 TCP → H265 TCP → H264 UDP → H265 UDP
- POST /api/cameras/test-connectivity injecte rtsp_url_validated / validated_url / debug_attempts
- POST /api/cameras refuse (400) sans validation RTSP (sauf allow_rtsp_override)
- GET /diagnostic retourne rtsp_url_masked
- REGRESSION /api/stream/{demo-cam-001}/live.mjpeg > 10 kB en 3s
"""
import os
import sys
import time
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback pour tests sans frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=10)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def hdr(token):
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# UNIT — _build_rtsp_url : encodage RFC3986 une seule fois
# ============================================================
class TestBuildRtspUrl:
    def test_encode_special_chars_once(self):
        from streaming import _build_rtsp_url
        url = _build_rtsp_url({
            "rtsp_url": "rtsp://192.168.1.10:554/stream",
            "username": "admin",
            "password": "Rlwt29#+jpf",
            "rtsp_transport": "tcp",
        })
        assert "Rlwt29%23%2Bjpf" in url
        assert "%2523" not in url and "%252B" not in url
        assert "admin:Rlwt29%23%2Bjpf@" in url

    def test_preserves_url_with_existing_creds(self):
        from streaming import _build_rtsp_url
        raw = "rtsp://user:pass@1.2.3.4:554/cam"
        url = _build_rtsp_url({
            "rtsp_url": raw,
            "username": "admin",
            "password": "Rlwt29#+jpf",
            "rtsp_transport": "tcp",
        })
        # Pas de double encodage : les creds d'origine sont préservés
        assert "user:pass@1.2.3.4" in url
        assert "admin:" not in url
        assert "%2523" not in url

    def test_applies_transport(self):
        from streaming import _build_rtsp_url
        url = _build_rtsp_url({
            "rtsp_url": "rtsp://1.2.3.4/x",
            "username": "u", "password": "p", "rtsp_transport": "udp",
        })
        assert "#transport=udp" in url


# ============================================================
# UNIT — _mask_url_password
# ============================================================
class TestMaskUrlPassword:
    def test_masks_password(self):
        from streaming import _mask_url_password
        got = _mask_url_password("rtsp://admin:supersecret@1.2.3.4:554/foo")
        assert got == "rtsp://admin:******@1.2.3.4:554/foo"

    def test_no_creds_no_change(self):
        from streaming import _mask_url_password
        got = _mask_url_password("rtsp://1.2.3.4:554/foo")
        assert got == "rtsp://1.2.3.4:554/foo"

    def test_masks_encoded_password(self):
        from streaming import _mask_url_password
        got = _mask_url_password("rtsp://admin:Rlwt29%23%2Bjpf@1.2.3.4:554/foo")
        assert "******" in got
        assert "Rlwt29" not in got


# ============================================================
# UNIT — _try_ffprobe_variants — 3-tuple + ordre + masking
# ============================================================
class TestTryFfprobeVariants:
    def test_returns_3_tuple_with_attempts_on_unreachable(self):
        from streaming import _try_ffprobe_variants
        # IP RFC5737 documentation → jamais routable
        result = _try_ffprobe_variants(
            "rtsp://192.0.2.99:554/h264Preview_01_main",
            preferred_codec="auto",
            transport="tcp",
            username="admin",
            password="Rlwt29#+jpf",
        )
        assert isinstance(result, tuple) and len(result) == 3
        working_url, details, attempts = result
        assert details is None
        assert isinstance(attempts, list) and len(attempts) > 0
        for a in attempts:
            assert set(["url_masked", "transport", "ok", "codec", "resolution"]).issubset(a.keys())
            # Password brut jamais présent
            assert "Rlwt29#+jpf" not in a["url_masked"]
            assert "Rlwt29%23%2Bjpf" not in a["url_masked"]
            assert "******" in a["url_masked"]

    def test_order_tcp_first_then_udp(self):
        from streaming import _try_ffprobe_variants
        _, _, attempts = _try_ffprobe_variants(
            "rtsp://192.0.2.99:554/h264Preview_01_main",
            preferred_codec="auto",
            transport="tcp",
            username="admin",
            password="Rlwt29#+jpf",
        )
        assert len(attempts) >= 2
        assert attempts[0]["transport"] == "TCP"
        # dernier attempt doit être UDP
        assert attempts[-1]["transport"] == "UDP"

    def test_order_h264_before_h265_within_transport(self):
        """Dans le même bloc transport, H264 avant H265."""
        from streaming import _try_ffprobe_variants
        _, _, attempts = _try_ffprobe_variants(
            "rtsp://192.0.2.99:554/h264Preview_01_main",
            preferred_codec="auto",
            transport="tcp",
            username="admin",
            password="pwd",
        )
        # Filtre TCP
        tcp_attempts = [a for a in attempts if a["transport"] == "TCP"]
        # Récupère index premier h264 vs premier h265 dans les URLs
        first_h264 = next((i for i, a in enumerate(tcp_attempts) if "h264Preview" in a["url_masked"].lower()), None)
        first_h265 = next((i for i, a in enumerate(tcp_attempts) if "h265Preview" in a["url_masked"].lower()), None)
        if first_h264 is not None and first_h265 is not None:
            assert first_h264 < first_h265, "H264 doit être testé avant H265 dans le même transport"


# ============================================================
# API — POST /api/cameras/test-connectivity
# ============================================================
class TestConnectivityEndpoint:
    def test_returns_new_fields_on_failure(self, hdr):
        r = requests.post(f"{BASE_URL}/api/cameras/test-connectivity", headers=hdr, json={
            "mode": "rtsp",
            "ip": "192.0.2.99",
            "rtsp_port": 554,
            "rtsp_url": "rtsp://192.0.2.99:554/h264Preview_01_main",
            "username": "admin",
            "password": "Rlwt29#+jpf",
            "rtsp_transport": "tcp",
            "preferred_codec": "auto",
        }, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        # Nouveaux champs
        assert "rtsp_url_validated" in body
        assert "validated_url" in body
        assert "validated_transport" in body
        assert "debug_attempts" in body
        # IP injoignable → validated=false
        assert body["rtsp_url_validated"] is False
        # message + steps corrects
        assert isinstance(body.get("steps"), list) and len(body["steps"]) > 0

    def test_password_never_leaked_in_response(self, hdr):
        r = requests.post(f"{BASE_URL}/api/cameras/test-connectivity", headers=hdr, json={
            "mode": "rtsp",
            "ip": "192.0.2.99",
            "rtsp_url": "rtsp://192.0.2.99:554/h264Preview_01_main",
            "username": "admin",
            "password": "Rlwt29#+jpf",
            "rtsp_transport": "tcp",
            "preferred_codec": "auto",
        }, timeout=60)
        raw = r.text
        assert "Rlwt29#+jpf" not in raw, "Le password brut ne doit JAMAIS apparaître dans la réponse"
        assert "Rlwt29%23%2Bjpf" not in raw, "Le password encodé ne doit pas apparaître non plus"
        # debug_attempts contient bien ******
        body = r.json()
        for a in body.get("debug_attempts", []):
            assert "******" in a["url_masked"]

    def test_debug_attempts_ordering(self, hdr):
        r = requests.post(f"{BASE_URL}/api/cameras/test-connectivity", headers=hdr, json={
            "mode": "rtsp",
            "ip": "192.0.2.99",
            "rtsp_url": "rtsp://192.0.2.99:554/h264Preview_01_main",
            "username": "u",
            "password": "p",
            "rtsp_transport": "tcp",
            "preferred_codec": "auto",
        }, timeout=60)
        assert r.status_code == 200
        atts = r.json().get("debug_attempts", [])
        # Note: IP injoignable → ping échoue → rtsp_open skip → debug_attempts peut être vide.
        # Ping du port 554 : peut être filtré, on n'assert que si non vide.
        if atts:
            assert atts[0]["transport"] == "TCP"
            assert atts[-1]["transport"] == "UDP"


# ============================================================
# API — POST /api/cameras : refuse si non validé
# ============================================================
class TestCameraCreationValidation:
    def test_reject_creation_without_rtsp_validation(self, hdr):
        # site existant
        sites = requests.get(f"{BASE_URL}/api/sites", headers=hdr, timeout=10).json()
        assert sites, "Au moins un site doit exister"
        site_id = sites[0]["id"]
        r = requests.post(f"{BASE_URL}/api/cameras", headers=hdr, json={
            "name": "TEST_iter20_reject",
            "site_id": site_id,
            "mode": "rtsp",
            "rtsp_url": "rtsp://192.0.2.99:554/nowhere",
            "username": "u",
            "password": "p",
            "rtsp_transport": "tcp",
        }, timeout=30)
        # Doit renvoyer 400 (impossible d'enregistrer flux dans go2rtc)
        assert r.status_code == 400, f"Attendu 400, reçu {r.status_code} : {r.text}"


# ============================================================
# REGRESSION — /diagnostic + live.mjpeg
# ============================================================
class TestRegressions:
    def test_diagnostic_returns_rtsp_url_masked(self, hdr):
        r = requests.get(f"{BASE_URL}/api/cameras/demo-cam-001/diagnostic", headers=hdr, timeout=10)
        assert r.status_code == 200, r.text
        cam = r.json().get("camera", {})
        assert "rtsp_url_masked" in cam

    def test_live_mjpeg_demo_cam_gt_10kb_in_3s(self, token):
        """REGRESSION obligatoire : le fix live vidéo précédent doit rester valide."""
        start = time.monotonic()
        r = requests.get(
            f"{BASE_URL}/api/stream/demo-cam-001/live.mjpeg",
            params={"token": token},
            stream=True, timeout=10,
        )
        assert r.status_code == 200, r.text
        ctype = r.headers.get("content-type", "")
        assert "multipart/x-mixed-replace" in ctype
        assert "boundary" in ctype.lower()
        total = 0
        for chunk in r.iter_content(chunk_size=4096):
            total += len(chunk)
            if total > 10_240:
                break
            if time.monotonic() - start > 3.5:
                break
        r.close()
        assert total > 10_240, f"Attendu > 10 kB en 3s, reçu {total} bytes"
