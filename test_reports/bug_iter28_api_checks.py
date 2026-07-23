"""Focused backend/API checks for iter28 ANPR thumbnails and Diagnostics Phase 1."""
from __future__ import annotations

import base64
import io
import json
import time
from datetime import datetime, timezone

import requests
from PIL import Image


BASE = "http://localhost:8001"
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


def rec(results, name, passed, detail=""):
    results.append({"name": name, "passed": bool(passed), "detail": detail})


def decode_dim(data_uri):
    if not data_uri or not isinstance(data_uri, str) or "," not in data_uri:
        return None
    raw = base64.b64decode(data_uri.split(",", 1)[1])
    img = Image.open(io.BytesIO(raw))
    return img.size


def age_seconds(iso_ts):
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).total_seconds()


def main():
    results = []
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=20)
    rec(results, "admin_login", r.status_code == 200 and r.json().get("access_token"), f"status={r.status_code}")
    r.raise_for_status()
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # Diagnostics cause classifier patterns.
    patterns = [
        ("Connection timed out (110)", "Timeout RTSP", 80),
        ("401 Unauthorized", "Authentification refusée", 80),
        ("No route to host", "Caméra hors ligne", 80),
        ("Traceback (most recent call last)", "Exception Python", 80),
    ]
    for text, expected, min_conf in patterns:
        r = s.post(f"{BASE}/api/diagnostics/camera/demo-cam-001/test-cause", json={"error_text": text}, headers=h, timeout=20)
        ok = r.status_code == 200 and r.json().get("cause") == expected and r.json().get("confidence", 0) >= min_conf and bool(r.json().get("detail"))
        rec(results, f"diagnostics_test_cause_{expected}", ok, f"status={r.status_code}, body={r.text[:300]}")

    r = s.get(f"{BASE}/api/diagnostics/journal?limit=10", headers=h, timeout=20)
    body = r.json() if r.status_code == 200 else {}
    rec(results, "diagnostics_journal_shape", r.status_code == 200 and isinstance(body.get("total"), int) and isinstance(body.get("items"), list), f"status={r.status_code}, body={r.text[:300]}")

    r = s.get(f"{BASE}/api/diagnostics/camera/demo-cam-001/summary", headers=h, timeout=20)
    body = r.json() if r.status_code == 200 else {}
    keys = {"camera_id", "window_days", "disconnects_30d", "reconnects_30d", "avg_reconnect_s", "mtbf_hours", "top_causes", "last_disconnect", "last_reconnect"}
    rec(results, "diagnostics_summary_shape", r.status_code == 200 and keys.issubset(body.keys()) and body.get("window_days") == 30 and isinstance(body.get("top_causes"), list), f"status={r.status_code}, keys={sorted(body.keys()) if isinstance(body, dict) else None}")

    r = s.get(f"{BASE}/api/diagnostics/camera/demo-cam-001/logs", headers=h, timeout=20)
    body = r.json() if r.status_code == 200 else {}
    rec(results, "diagnostics_logs_shape", r.status_code == 200 and isinstance(body.get("backend"), list) and isinstance(body.get("go2rtc"), list), f"status={r.status_code}, body={r.text[:300]}")

    r = s.get(f"{BASE}/api/diagnostics/camera/demo-cam-001/report", headers=h, timeout=20)
    body = r.json() if r.status_code == 200 else {}
    report_text = r.text
    report_ok = (
        r.status_code == 200
        and {"generated_at", "camera", "go2rtc", "summary", "recent_incidents", "recent_logs"}.issubset(body.keys())
        and {"id", "name", "rtsp_url_masked"}.issubset((body.get("camera") or {}).keys())
        and {"source_registered", "hd_registered", "sd_registered"}.issubset((body.get("go2rtc") or {}).keys())
        and "Admin@2026" not in report_text
        and not (body.get("camera", {}).get("rtsp_url_masked", "").count(":") >= 2 and "***" not in body.get("camera", {}).get("rtsp_url_masked", "") and "@" in body.get("camera", {}).get("rtsp_url_masked", ""))
    )
    rec(results, "diagnostics_report_shape_no_plain_password", report_ok, f"status={r.status_code}, rtsp_url_masked={(body.get('camera') or {}).get('rtsp_url_masked') if isinstance(body, dict) else None}")

    # Poll briefly for a recent demo-cam-002 event with HD scene thumbnail.
    event_ok = False
    event_detail = "no recent event found"
    deadline = time.time() + 40
    while time.time() < deadline and not event_ok:
        r = s.get(f"{BASE}/api/events?camera_id=demo-cam-002&limit=3", headers=h, timeout=20)
        if r.status_code == 200:
            for ev in r.json():
                try:
                    dim = decode_dim(ev.get("thumbnail"))
                    age = age_seconds(ev.get("timestamp"))
                    event_detail = f"id={ev.get('id')}, type={ev.get('type')}, age={age:.1f}s, dim={dim}"
                    if age < 90 and dim and dim[0] >= 640 and dim[1] >= 360:
                        event_ok = True
                        break
                except Exception as e:
                    event_detail = f"decode_error={e}"
        time.sleep(5)
    rec(results, "recent_events_have_hd_thumbnail", event_ok, event_detail)

    # Poll for newest plate with HD frame_thumb + non-empty crops.
    plate_ok = False
    plate_detail = "no plate found"
    deadline = time.time() + 80
    while time.time() < deadline and not plate_ok:
        r = s.get(f"{BASE}/api/plates?camera_id=demo-cam-002&limit=3", headers=h, timeout=20)
        if r.status_code == 200:
            for p in r.json():
                try:
                    frame_dim = decode_dim(p.get("frame_thumb"))
                    veh_dim = decode_dim(p.get("vehicle_crop"))
                    plate_dim = decode_dim(p.get("plate_crop"))
                    plate_detail = f"plate={p.get('plate')}, age={age_seconds(p.get('timestamp')):.1f}s, frame={frame_dim}, vehicle={veh_dim}, plate_crop={plate_dim}"
                    if frame_dim and frame_dim[0] >= 640 and frame_dim[1] >= 360 and veh_dim and plate_dim:
                        plate_ok = True
                        break
                except Exception as e:
                    plate_detail = f"decode_error={e}"
        time.sleep(5)
    rec(results, "newest_plate_has_hd_frame_and_crops", plate_ok, plate_detail)

    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    if not all(x["passed"] for x in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()