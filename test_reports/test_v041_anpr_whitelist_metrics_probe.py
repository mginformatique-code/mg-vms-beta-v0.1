#!/usr/bin/env python3
"""Focused runtime probe for MG-VMS v0.4.1 FastALPR camera whitelist.

Disables fast-alpr on demo-cam-002, watches plate persistence and pipeline
metrics for ~60s, then restores fast-alpr.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import requests

BASE = os.environ.get("MGVMS_BASE_URL", "https://video-command-6.preview.emergentagent.com")
CAMERA_ID = "demo-cam-002"
DISABLED = ["yolo-detection", "bytetrack"]
ENABLED = ["yolo-detection", "bytetrack", "fast-alpr"]


def request(method: str, path: str, token: str | None = None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, BASE + path, headers=headers, timeout=20, **kwargs)


def plate_total(token: str) -> int:
    resp = request("GET", f"/api/plates?camera_id={CAMERA_ID}&limit=1", token)
    resp.raise_for_status()
    return int(resp.headers.get("X-Total-Count", len(resp.json())))


def camera_metric(token: str) -> dict:
    resp = request("GET", "/api/diagnostics/pipeline-metrics", token)
    resp.raise_for_status()
    cam = ((resp.json().get("cameras") or {}).get(CAMERA_ID)) or {}
    stages = cam.get("stages") or {}
    return {
        "camera_present": bool(cam),
        "alpr_ms": stages.get("alpr_ms"),
        "yolo_ms": stages.get("yolo_ms"),
        "total_ms": stages.get("total_ms"),
        "raw_keys": sorted(cam.keys()),
    }


def debug_snapshot(token: str) -> dict:
    resp = request("GET", f"/api/ai/debug/{CAMERA_ID}", token)
    if not resp.ok:
        return {"status": resp.status_code, "body": resp.text[:200]}
    body = resp.json()
    body.pop("frame_preview", None)
    return {
        "status": resp.status_code,
        "timestamp": body.get("timestamp"),
        "timings": body.get("timings"),
        "plates_ocr": body.get("plates_ocr"),
        "plate_attempts_count": len(body.get("plate_attempts") or []),
        "vehicles_count": len(body.get("vehicles") or []),
    }


def main() -> int:
    out = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "camera_id": CAMERA_ID,
        "disabled_plugins": DISABLED,
        "samples": [],
        "failures": [],
    }
    token = None
    original = None
    try:
        login = request("POST", "/api/auth/login", json={"email": "admin@mg-vms.com", "password": "Admin@2026"})
        out["login_status"] = login.status_code
        login.raise_for_status()
        token = login.json().get("access_token")
        out["login_has_token"] = bool(token)
        if not token:
            out["failures"].append("login returned no token")
            return 1

        cam_resp = request("GET", f"/api/cameras/{CAMERA_ID}", token)
        out["get_camera_status"] = cam_resp.status_code
        cam_resp.raise_for_status()
        original = cam_resp.json()
        out["original_enabled_plugins"] = original.get("enabled_plugins")

        disabled_body = dict(original)
        disabled_body["detect_enabled"] = True
        disabled_body["enabled_plugins"] = DISABLED
        put = request("PUT", f"/api/cameras/{CAMERA_ID}", token, json=disabled_body)
        out["disable_status"] = put.status_code
        put.raise_for_status()
        persisted = request("GET", f"/api/cameras/{CAMERA_ID}", token)
        persisted.raise_for_status()
        out["persisted_enabled_plugins_after_disable"] = persisted.json().get("enabled_plugins")

        if "fast-alpr" in (out["persisted_enabled_plugins_after_disable"] or []):
            out["failures"].append("fast-alpr still persisted after disable")

        before = plate_total(token)
        out["plates_before"] = before
        for elapsed in [0, 10, 20, 30, 45, 60]:
            if elapsed:
                time.sleep(elapsed - (out["samples"][-1]["elapsed_s"] if out["samples"] else 0))
            sample = {
                "elapsed_s": elapsed,
                "plate_total": plate_total(token),
                "metric": camera_metric(token),
                "debug": debug_snapshot(token),
            }
            out["samples"].append(sample)

        after = out["samples"][-1]["plate_total"]
        out["plates_after_60s"] = after
        out["plates_delta_60s"] = after - before
        if after != before:
            out["failures"].append(f"new plates persisted while fast-alpr disabled: delta={after-before}")

        final_alpr = ((out["samples"][-1].get("metric") or {}).get("alpr_ms") or {}).get("avg")
        out["final_pipeline_alpr_ms_avg"] = final_alpr
        if final_alpr is None or float(final_alpr) > 1.0:
            out["failures"].append(f"alpr_ms.avg expected <=1.0 after 60s disabled, got {final_alpr}")
    finally:
        if token and original:
            restore = dict(original)
            restore["detect_enabled"] = True
            restore["enabled_plugins"] = ENABLED
            try:
                r = request("PUT", f"/api/cameras/{CAMERA_ID}", token, json=restore)
                out["cleanup_status"] = r.status_code
                out["cleanup_enabled_plugins"] = r.json().get("enabled_plugins") if r.ok else r.text[:200]
            except Exception as exc:  # pragma: no cover
                out["cleanup_error"] = f"{type(exc).__name__}: {exc}"
        out["finished_at"] = datetime.now(timezone.utc).isoformat()
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if out.get("failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())