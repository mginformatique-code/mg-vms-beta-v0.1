#!/usr/bin/env python3
"""Final focused API verification for FastALPR enabled_plugins whitelist."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

import requests

BASE = "https://video-command-6.preview.emergentagent.com"
CAMERA_ID = "demo-cam-002"


def request(method, path, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, BASE + path, headers=headers, timeout=20, **kwargs)


def plate_total(token):
    r = request("GET", f"/api/plates?camera_id={CAMERA_ID}&limit=100", token)
    r.raise_for_status()
    return int(r.headers.get("X-Total-Count", len(r.json()))), r.json()


def main():
    out = {"started_at": datetime.now(timezone.utc).isoformat(), "camera_id": CAMERA_ID, "failures": []}
    token = None
    cam_body = None
    try:
        login = request("POST", "/api/auth/login", json={"email": "admin@mg-vms.com", "password": "Admin@2026"})
        out["login_status"] = login.status_code
        login.raise_for_status()
        token = login.json().get("access_token")
        out["login_has_access_token"] = bool(token)
        if not token:
            out["failures"].append("login did not return access_token")
            return out

        cam = request("GET", f"/api/cameras/{CAMERA_ID}", token)
        out["get_camera_status"] = cam.status_code
        cam.raise_for_status()
        cam_body = cam.json()
        out["original_enabled_plugins"] = cam_body.get("enabled_plugins")

        disabled_body = dict(cam_body)
        disabled_body["detect_enabled"] = True
        disabled_body["enabled_plugins"] = ["yolo-detection", "bytetrack"]
        put = request("PUT", f"/api/cameras/{CAMERA_ID}", token, json=disabled_body)
        out["put_disable_fast_alpr_status"] = put.status_code
        put.raise_for_status()
        persisted = request("GET", f"/api/cameras/{CAMERA_ID}", token).json()
        out["persisted_disabled_enabled_plugins"] = persisted.get("enabled_plugins")
        if "fast-alpr" in (persisted.get("enabled_plugins") or []):
            out["failures"].append("fast-alpr remained in enabled_plugins after disable")

        before, before_rows = plate_total(token)
        out["plates_before_total"] = before
        out["plates_before_latest"] = before_rows[0] if before_rows else None
        time.sleep(35)
        after, after_rows = plate_total(token)
        out["plates_after_total"] = after
        out["plates_after_latest"] = after_rows[0] if after_rows else None
        out["plates_delta_35s"] = after - before
        if after != before:
            out["failures"].append(f"new plates appeared while fast-alpr disabled: delta={after-before}")

        metrics = request("GET", "/api/diagnostics/pipeline-metrics", token)
        out["pipeline_metrics_status"] = metrics.status_code
        metrics.raise_for_status()
        metrics_json = metrics.json()
        cam_metrics = (metrics_json.get("cameras") or {}).get(CAMERA_ID)
        out["pipeline_metrics_camera_present"] = cam_metrics is not None
        out["pipeline_metrics_camera"] = cam_metrics
        alpr_avg = (((cam_metrics or {}).get("stages") or {}).get("alpr_ms") or {}).get("avg")
        out["pipeline_alpr_ms_avg"] = alpr_avg
        if cam_metrics is None:
            out["failures"].append("pipeline metrics missing demo-cam-002 while detect_enabled=true/status=online")
        elif alpr_avg is None or float(alpr_avg) > 1.0:
            out["failures"].append(f"alpr_ms.avg expected <=1.0, got {alpr_avg}")

        debug = request("GET", f"/api/ai/debug/{CAMERA_ID}", token)
        out["ai_debug_status"] = debug.status_code
        if debug.ok:
            out["ai_debug"] = debug.json()
    finally:
        if token and cam_body:
            restore = dict(cam_body)
            restore["detect_enabled"] = True
            restore["enabled_plugins"] = ["yolo-detection", "bytetrack", "fast-alpr"]
            try:
                r = request("PUT", f"/api/cameras/{CAMERA_ID}", token, json=restore)
                out["cleanup_reenable_fast_alpr_status"] = r.status_code
                out["cleanup_enabled_plugins"] = r.json().get("enabled_plugins") if r.ok else r.text[:300]
            except Exception as exc:  # pragma: no cover - diagnostic only
                out["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        out["finished_at"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


if __name__ == "__main__":
    result = main()
    sys.exit(1 if result.get("failures") else 0)