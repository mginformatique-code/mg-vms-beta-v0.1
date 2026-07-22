"""MG-VMS — Tests reconnaissance faciale (iter 22)."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://video-command-6.preview.emergentagent.com").rstrip("/")
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}

REAL_FACE = "/root/.venv/lib/python3.11/site-packages/insightface/data/images/Tom_Hanks_54745.png"
NO_FACE = "/tmp/notaface.jpg"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def created_face_ids():
    ids = []
    yield ids
    # cleanup
    r = requests.post(f"{BASE_URL}/api/auth/login", json=ADMIN, timeout=10)
    if r.status_code == 200:
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        for fid in ids:
            requests.delete(f"{BASE_URL}/api/plugins/face_recognition/faces/{fid}", headers=h, timeout=10)


def test_availability(headers):
    r = requests.get(f"{BASE_URL}/api/plugins/face_recognition/availability", headers=headers, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["installed"] is True
    assert data["provider"] == "insightface"
    assert "notes" in data


def test_add_face_no_photo(headers, created_face_ids):
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces",
                       headers=headers, json={"name": "TEST_iter22_no_photo", "watchlist": False}, timeout=10)
    assert r.status_code == 200, r.text
    d = r.json()
    assert "id" in d and d["name"] == "TEST_iter22_no_photo"
    assert d.get("thumbnail") is None
    assert d.get("photo_meta") is None
    assert "encoding" not in d
    created_face_ids.append(d["id"])


def test_list_faces_excludes_encoding(headers, created_face_ids):
    r = requests.get(f"{BASE_URL}/api/plugins/face_recognition/faces", headers=headers, timeout=10)
    assert r.status_code == 200
    faces = r.json()
    assert isinstance(faces, list)
    for f in faces:
        assert "encoding" not in f, "encoding must never be returned"


def test_upload_non_image_400(headers, created_face_ids):
    # Create a face for the upload
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces",
                       headers=headers, json={"name": "TEST_iter22_nonimg", "watchlist": False}, timeout=10)
    fid = r.json()["id"]
    created_face_ids.append(fid)
    files = {"photo": ("bad.txt", b"not an image at all", "text/plain")}
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces/{fid}/photo",
                      headers=headers, files=files, timeout=15)
    assert r.status_code == 400, r.text


def test_upload_no_face_400(headers, created_face_ids):
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces",
                       headers=headers, json={"name": "TEST_iter22_noface", "watchlist": False}, timeout=10)
    fid = r.json()["id"]
    created_face_ids.append(fid)
    with open(NO_FACE, "rb") as fp:
        files = {"photo": ("notaface.jpg", fp.read(), "image/jpeg")}
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces/{fid}/photo",
                      headers=headers, files=files, timeout=120)  # first model load
    assert r.status_code == 400, r.text
    assert "Aucun visage" in r.json().get("detail", ""), r.text


def test_upload_too_large_400(headers, created_face_ids):
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces",
                       headers=headers, json={"name": "TEST_iter22_big", "watchlist": False}, timeout=10)
    fid = r.json()["id"]
    created_face_ids.append(fid)
    big = b"\xff" * (9 * 1024 * 1024)
    files = {"photo": ("big.jpg", big, "image/jpeg")}
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces/{fid}/photo",
                      headers=headers, files=files, timeout=30)
    assert r.status_code == 400, r.text
    assert "volumineuse" in r.json().get("detail", "").lower(), r.text


def test_upload_real_face_success(headers, created_face_ids):
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces",
                       headers=headers, json={"name": "TEST_iter22_real", "watchlist": True}, timeout=10)
    fid = r.json()["id"]
    created_face_ids.append(fid)
    with open(REAL_FACE, "rb") as fp:
        files = {"photo": ("face.png", fp.read(), "image/png")}
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces/{fid}/photo",
                      headers=headers, files=files, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["embedding_dim"] == 512
    assert d["has_thumbnail"] is True
    assert "det_score" in d["meta"]
    assert "bbox" in d["meta"] and len(d["meta"]["bbox"]) == 4

    # verify persistence — thumbnail + photo_meta returned in list, encoding excluded
    r2 = requests.get(f"{BASE_URL}/api/plugins/face_recognition/faces", headers=headers, timeout=10)
    face = next((f for f in r2.json() if f["id"] == fid), None)
    assert face is not None
    assert face.get("thumbnail", "").startswith("data:image/jpeg;base64,")
    assert face.get("photo_meta") is not None
    assert "encoding" not in face


def test_config_enable_and_healthy(headers, created_face_ids):
    # ensure at least one face with encoding exists (from previous test)
    r = requests.put(f"{BASE_URL}/api/plugins/face_recognition/config",
                     headers=headers, json={"enabled": True, "distance_threshold": 0.55,
                                             "alert_on_watchlist": True, "alert_on_unknown": False}, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True

    r = requests.get(f"{BASE_URL}/api/plugins", headers=headers, timeout=15)
    assert r.status_code == 200
    plugins = r.json()
    face = next((p for p in plugins if p["id"] == "face_recognition"), None)
    assert face is not None
    h = face.get("health") or {}
    assert h.get("configured") is True, face
    assert h.get("healthy") is True, face


def test_plugins_regression_count(headers):
    r = requests.get(f"{BASE_URL}/api/plugins", headers=headers, timeout=15)
    assert r.status_code == 200
    plugins = r.json()
    ids = {p["id"] for p in plugins}
    assert len(plugins) >= 8, f"Expected >=8 plugins, got {len(plugins)}: {ids}"
    # check core plugins still present
    for pid in ["anpr", "tracking", "parking", "access_control", "face_recognition"]:
        assert pid in ids, f"Plugin {pid} missing"


def test_delete_face(headers):
    r = requests.post(f"{BASE_URL}/api/plugins/face_recognition/faces",
                       headers=headers, json={"name": "TEST_iter22_del", "watchlist": False}, timeout=10)
    fid = r.json()["id"]
    r = requests.delete(f"{BASE_URL}/api/plugins/face_recognition/faces/{fid}", headers=headers, timeout=10)
    assert r.status_code == 200, r.text
    r = requests.get(f"{BASE_URL}/api/plugins/face_recognition/faces", headers=headers, timeout=10)
    assert not any(f["id"] == fid for f in r.json())


def test_engine_module_direct():
    """Verify face_recognition_engine module functions work."""
    import sys
    sys.path.insert(0, "/app/backend")
    from face_recognition_engine import extract_embedding, analyze_frame, availability
    a = availability()
    assert a["installed"] is True

    with open(NO_FACE, "rb") as f:
        emb, meta = extract_embedding(f.read())
    assert emb is None
    assert "Aucun visage" in meta.get("error", "")

    with open(REAL_FACE, "rb") as f:
        emb, meta = extract_embedding(f.read())
    assert emb is not None
    assert len(emb) == 512
    assert "det_score" in meta

    # analyze_frame with empty known → []
    import numpy as np
    dummy = np.zeros((100, 100, 3), dtype=np.uint8)
    assert analyze_frame(dummy, []) == []
