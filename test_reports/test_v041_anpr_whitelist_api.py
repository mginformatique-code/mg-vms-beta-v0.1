#!/usr/bin/env python3
"""Focused backend verification for MG-VMS v0.4.1 FastALPR whitelist bug.

Checks that demo-cam-002 can be configured without fast-alpr, no new plates are
persisted during a 35s AI window, ALPR metrics stay near zero, and requested
regression endpoints still respond.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests


BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://video-command-6.preview.emergentagent.com").rstrip("/")
EMAIL = os.environ.get("MGVMS_TEST_EMAIL", "admin@mg-vms.com")
PASSWORD = os.environ.get("MGVMS_TEST_PASSWORD", "Admin@2026")
CAMERA_ID = "demo-cam-002"


def fail(step: str, detail: str, status: int = 1):
    print(json.dumps({"ok": False, "step": step, "detail": detail}, ensure_ascii=False, indent=2))
    sys.exit(status)


def req(method: str, path: str, token: str | None = None, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers.setdefault("Content-Type", "application/json")
    return requests.request(method, f"{BASE}{path}", headers=headers, timeout=20, **kwargs)


def assert_status(resp: requests.Response, expected: int, step: str):
    if resp.status_code != expected:
        fail(step, f"HTTP {resp.status_code}, expected {expected}: {resp.text[:500]}")


def total_plates(token: str) -> tuple[int, list[dict]]:
    resp = req("GET", f"/api/plates?camera_id={CAMERA_ID}&limit=100", token)
    assert_status(resp, 200, "GET /api/plates")
    try:
        header_total = int(resp.headers.get("X-Total-Count", ""))
    except ValueError:
        header_total = len(resp.json())
    return header_total, resp.json()


def main():
    print(f"BASE={BASE}")
    result: dict = {"base": BASE, "camera_id": CAMERA_ID, "started_at": datetime.now(timezone.utc).isoformat()}

    # 1) Login regression.
    login = req("POST", "/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert_status(login, 200, "POST /api/auth/login")
    token = login.json().get("access_token")
    if not token:
        fail("POST /api/auth/login", f"No access_token in response: {login.text[:300]}")
    result["login"] = {"ok": True, "user": login.json().get("user", {}).get("email")}

    # 2) Ensure demo-cam-002 exists and persist whitelist WITHOUT fast-alpr.
    cam_resp = req("GET", f"/api/cameras/{CAMERA_ID}", token)
    assert_status(cam_resp, 200, f"GET /api/cameras/{CAMERA_ID} before")
    cam = cam_resp.json()
    original_plugins = cam.get("enabled_plugins") or []
    original_detect = cam.get("detect_enabled")
    result["camera_before"] = {"enabled_plugins": original_plugins, "detect_enabled": original_detect}

    cam_patch = dict(cam)
    cam_patch.update({"detect_enabled": True, "enabled_plugins": ["yolo-detection", "bytetrack"]})
    # API PUT schema requires name/site_id and accepts full camera body; password is omitted intentionally.
    put_skip = req("PUT", f"/api/cameras/{CAMERA_ID}", token, json=cam_patch)
    assert_status(put_skip, 200, f"PUT /api/cameras/{CAMERA_ID} without fast-alpr")
    cam_after = req("GET", f"/api/cameras/{CAMERA_ID}", token)
    assert_status(cam_after, 200, f"GET /api/cameras/{CAMERA_ID} after skip config")
    enabled = cam_after.json().get("enabled_plugins") or []
    if "fast-alpr" in enabled:
        fail("enabled_plugins persistence", f"fast-alpr still present after disabling: {enabled}")
    if sorted(enabled) != ["bytetrack", "yolo-detection"]:
        fail("enabled_plugins persistence", f"Unexpected enabled_plugins after disabling: {enabled}")
    result["camera_skip_config"] = {"enabled_plugins": enabled, "detect_enabled": cam_after.json().get("detect_enabled")}

    # 3) Count plates before/after several AI cycles.
    before_total, before_rows = total_plates(token)
    result["plates_before"] = {"total": before_total, "latest": before_rows[0] if before_rows else None}
    print(f"Waiting 35s with fast-alpr disabled on {CAMERA_ID}...")
    time.sleep(35)
    after_total, after_rows = total_plates(token)
    result["plates_after"] = {"total": after_total, "latest": after_rows[0] if after_rows else None, "delta": after_total - before_total}
    if after_total != before_total:
        fail("ANPR disabled no-new-plates window", json.dumps(result["plates_after"], ensure_ascii=False))

    # 4) Diagnostics: ALPR avg should be zero/near zero for this camera.
    metrics_resp = req("GET", "/api/diagnostics/pipeline-metrics", token)
    assert_status(metrics_resp, 200, "GET /api/diagnostics/pipeline-metrics")
    metrics_json = metrics_resp.json()
    cam_metrics = (metrics_json.get("cameras") or {}).get(CAMERA_ID)
    alpr_avg = None
    if cam_metrics:
        alpr_avg = ((cam_metrics.get("stages") or {}).get("alpr_ms") or {}).get("avg")
    result["pipeline_metrics"] = {"camera_present": cam_metrics is not None, "alpr_ms_avg": alpr_avg, "raw": cam_metrics}
    if cam_metrics is None:
        fail("GET /api/diagnostics/pipeline-metrics", f"No metrics for {CAMERA_ID}: {json.dumps(metrics_json)[:1000]}")
    if alpr_avg is None or float(alpr_avg) > 1.0:
        fail("ALPR metrics near zero", f"Expected alpr_ms.avg <= 1.0 when fast-alpr disabled, got {alpr_avg}")

    # 5) Re-enable fast-alpr and verify persistence.
    cam_enable = dict(cam_after.json())
    cam_enable.update({"detect_enabled": True, "enabled_plugins": ["yolo-detection", "bytetrack", "fast-alpr"]})
    put_enable = req("PUT", f"/api/cameras/{CAMERA_ID}", token, json=cam_enable)
    assert_status(put_enable, 200, f"PUT /api/cameras/{CAMERA_ID} with fast-alpr")
    cam_final_resp = req("GET", f"/api/cameras/{CAMERA_ID}", token)
    assert_status(cam_final_resp, 200, f"GET /api/cameras/{CAMERA_ID} after enable")
    final_plugins = cam_final_resp.json().get("enabled_plugins") or []
    if "fast-alpr" not in final_plugins:
        fail("enabled_plugins re-enable persistence", f"fast-alpr missing after enable: {final_plugins}")
    result["camera_final"] = {"enabled_plugins": final_plugins}

    # 6) Regression endpoint checks.
    bus = req("GET", "/api/plugins/bus", token)
    assert_status(bus, 200, "GET /api/plugins/bus")
    bus_json = bus.json()
    bus_total = (bus_json.get("counts") or {}).get("total")
    result["plugins_bus_total"] = bus_total
    if bus_total != 50:
        fail("GET /api/plugins/bus", f"Expected 50 plugins, got {bus_total}")

    frame = req("GET", "/api/diagnostics/frame-source", token)
    assert_status(frame, 200, "GET /api/diagnostics/frame-source")
    frame_json = frame.json()
    workers = frame_json.get("workers") or {}
    alive_workers = [cid for cid, w in workers.items() if w.get("alive")]
    result["frame_source"] = {"worker_count": len(workers), "alive_workers": alive_workers}
    if not alive_workers:
        fail("GET /api/diagnostics/frame-source", f"Expected at least one alive worker: {json.dumps(frame_json)[:1000]}")

    catalog = req("GET", "/api/plugins/catalog", token)
    assert_status(catalog, 200, "GET /api/plugins/catalog")
    catalog_json = catalog.json()
    result["plugins_catalog"] = {"total": catalog_json.get("total"), "group_count": len(catalog_json.get("groups") or [])}
    if catalog_json.get("total") != 50 or not catalog_json.get("groups"):
        fail("GET /api/plugins/catalog", f"Expected total=50 and grouped catalog, got {result['plugins_catalog']}")

    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["ok"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()