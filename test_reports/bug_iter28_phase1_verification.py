"""Focused verification for ANPR lazy-thumbnail regression + Diagnostic Phase 1.

Test artifact only; does not modify product code.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import requests
from PIL import Image


APP = Path("/app")
BACKEND = APP / "backend"
FRONTEND_ENV = APP / "frontend" / ".env"


def read_env_file(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return values


for key, value in read_env_file(BACKEND / ".env").items():
    os.environ.setdefault(key, value)
sys.path.insert(0, str(BACKEND))


def record(results: list[dict], name: str, passed: bool, detail: str = "") -> None:
    results.append({"name": name, "passed": bool(passed), "detail": detail})


async def direct_lazy_checks(results: list[dict]) -> None:
    import numpy as np
    import ai_engine as AI
    from diagnostics import capture_stream_metrics

    old_is_armed = AI._is_armed
    old_rules = AI._get_scenario_rules
    old_raise = AI._raise_scenario_alert
    old_ensure = AI._ensure_frame_thumb
    try:
        rules = {
            "intrusion_nocturne": {"enabled": True, "night_start": 22, "night_end": 6, "webhook": "", "label": "intrusion"},
            "vol_vehicule": {"enabled": True, "night_start": 22, "night_end": 6, "webhook": "", "label": "vol"},
            "rodeur": {"enabled": True, "consecutive": 5, "webhook": "", "label": "rodeur"},
            "attroupement": {"enabled": True, "min_persons": 5, "webhook": "", "label": "attroupement"},
            "vive_allure": {"enabled": True, "motion_pct": 90.0, "webhook": "", "label": "vive"},
            "collision": {"enabled": True, "iou": 0.5, "webhook": "", "label": "collision"},
            "enfant_route": {"enabled": True, "ratio": 0.5, "webhook": "", "label": "enfant"},
        }
        call_count = {"n": 0}

        def spy(res):
            call_count["n"] += 1
            return "thumb"

        AI._is_armed = AsyncMock(return_value=True)
        AI._get_scenario_rules = AsyncMock(return_value=rules)
        AI._raise_scenario_alert = AsyncMock()
        AI._ensure_frame_thumb = spy
        result = {"_img_bgr": np.full((720, 1280, 3), 128, dtype="uint8"), "detections": [], "motion_pct": 0.0}
        await AI._evaluate_scenarios({"id": "demo-cam-002", "name": "Trafic"}, result, datetime.now(timezone.utc))
        record(
            results,
            "direct_evaluate_scenarios_no_detections_no_encoding",
            call_count["n"] == 0,
            f"_ensure_frame_thumb calls={call_count['n']} expected=0",
        )
    finally:
        AI._is_armed = old_is_armed
        AI._get_scenario_rules = old_rules
        AI._raise_scenario_alert = old_raise
        AI._ensure_frame_thumb = old_ensure

    try:
        metrics = await capture_stream_metrics({"id": "demo-cam-001", "codec": "H264", "resolution": "1280x720", "fps": 15})
        required = all(k in metrics for k in ("codec", "resolution", "url_masked"))
        record(results, "capture_stream_metrics_no_exception", required, json.dumps(metrics, ensure_ascii=False))
    except Exception as exc:
        record(results, "capture_stream_metrics_no_exception", False, repr(exc))


def api_checks(results: list[dict]) -> str | None:
    frontend_env = read_env_file(FRONTEND_ENV)
    base = frontend_env.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/") + "/api"
    sess = requests.Session()
    login = sess.post(f"{base}/auth/login", json={"email": "admin@mg-vms.com", "password": "Admin@2026"}, timeout=15)
    ok = login.status_code == 200 and login.json().get("access_token")
    record(results, "admin_login", ok, f"status={login.status_code} body={login.text[:200]}")
    if not ok:
        return None
    token = login.json()["access_token"]
    sess.headers.update({"Authorization": f"Bearer {token}"})

    expected_causes = {
        "Connection timed out": "Timeout RTSP",
        "401 Unauthorized": "Authentification refusée",
        "No route to host": "Caméra hors ligne",
        "Traceback (most recent call last)": "Exception Python",
        "invalid NAL unit": "GOP corrompu",
    }
    for text, expected in expected_causes.items():
        r = sess.post(f"{base}/diagnostics/camera/demo-cam-001/test-cause", json={"error_text": text}, timeout=15)
        try:
            data = r.json()
        except Exception:
            data = {}
        passed = r.status_code == 200 and data.get("cause") == expected and int(data.get("confidence") or 0) >= 80
        record(results, f"diagnostics_test_cause_{expected}", passed, f"status={r.status_code} data={data}")

    r = sess.get(f"{base}/diagnostics/journal", params={"limit": 10}, timeout=15)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    record(results, "diagnostics_journal_shape", r.status_code == 200 and "total" in data and isinstance(data.get("items"), list), f"status={r.status_code} data={data}")

    r = sess.get(f"{base}/diagnostics/camera/demo-cam-001/summary", timeout=15)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    summary_keys = {"camera_id", "window_days", "disconnects_30d", "mtbf_hours", "avg_reconnect_s", "top_causes", "last_disconnect", "last_reconnect"}
    record(results, "diagnostics_summary_shape", r.status_code == 200 and summary_keys.issubset(data.keys()) and data.get("window_days") == 30, f"status={r.status_code} data={data}")

    r = sess.get(f"{base}/diagnostics/camera/demo-cam-001/logs", timeout=15)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    record(results, "diagnostics_logs_shape", r.status_code == 200 and isinstance(data.get("backend"), list) and isinstance(data.get("go2rtc"), list), f"status={r.status_code} data_keys={list(data) if isinstance(data, dict) else type(data)}")

    r = sess.get(f"{base}/diagnostics/camera/demo-cam-001/report", timeout=20)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    report_json = json.dumps(data, ensure_ascii=False)
    has_sections = r.status_code == 200 and all(k in data for k in ("camera", "go2rtc", "summary", "recent_incidents", "recent_logs"))
    # Demo RTSP URLs may not include credentials; accept either no credentials at all or masked credentials.
    camera = data.get("camera") if isinstance(data, dict) else {}
    rtsp_masked = str((camera or {}).get("rtsp_url_masked") or "")
    has_plain_secret = "Admin@2026" in report_json or "test123" in report_json or "password\":" in report_json.lower()
    rtsp_safe = (not rtsp_masked) or (":***@" in rtsp_masked) or ("@" not in rtsp_masked)
    record(results, "diagnostics_report_shape_and_masking", has_sections and (not has_plain_secret) and rtsp_safe, f"status={r.status_code} has_sections={has_sections} rtsp_url_masked={rtsp_masked!r} has_plain_secret={has_plain_secret} sample={report_json[:300]}")

    deadline = time.time() + 75
    event_detail = "no matching recent event polled"
    event_passed = False
    while time.time() < deadline:
        r = sess.get(f"{base}/events", params={"camera_id": "demo-cam-002", "limit": 3}, timeout=20)
        if r.status_code == 200:
            events = r.json()
            now = datetime.now(timezone.utc)
            if events:
                ev = events[0]
                try:
                    ts = datetime.fromisoformat(str(ev.get("timestamp", "")).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age = (now - ts).total_seconds()
                except Exception:
                    age = 999999
                thumb = ev.get("thumbnail") or ""
                event_detail = f"latest_type={ev.get('type')} age_s={age:.1f} thumb_len={len(thumb)}"
                if age < 90 and thumb.startswith("data:image/jpeg;base64,"):
                    try:
                        img = Image.open(io.BytesIO(base64.b64decode(thumb.split(",", 1)[1])))
                        event_detail += f" size={img.size}"
                        event_passed = img.size[0] >= 640 and img.size[1] >= 360
                        break
                    except Exception as exc:
                        event_detail += f" decode_error={exc!r}"
        else:
            event_detail = f"status={r.status_code} body={r.text[:200]}"
        time.sleep(5)
    record(results, "recent_demo_cam_002_event_has_hd_jpeg_thumbnail", event_passed, event_detail)
    return base


async def main() -> None:
    results: list[dict] = []
    await direct_lazy_checks(results)
    base = api_checks(results)
    print(json.dumps({"base": base, "results": results}, ensure_ascii=False, indent=2))
    if not all(item["passed"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())