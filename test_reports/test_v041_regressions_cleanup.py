#!/usr/bin/env python3
"""Cleanup/regression checks after focused ANPR whitelist verification."""
from __future__ import annotations

import json
import requests

BASE = "https://video-command-6.preview.emergentagent.com"
CAMERA_ID = "demo-cam-002"


def main():
    out = {}
    login = requests.post(f"{BASE}/api/auth/login", json={"email": "admin@mg-vms.com", "password": "Admin@2026"}, timeout=20)
    out["login_status"] = login.status_code
    login.raise_for_status()
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    out["login_has_access_token"] = bool(token)

    cam = requests.get(f"{BASE}/api/cameras/{CAMERA_ID}", headers=headers, timeout=20)
    out["get_camera_before_status"] = cam.status_code
    cam.raise_for_status()
    body = cam.json()
    body["detect_enabled"] = True
    body["enabled_plugins"] = ["yolo-detection", "bytetrack", "fast-alpr"]
    put = requests.put(f"{BASE}/api/cameras/{CAMERA_ID}", headers=headers, json=body, timeout=20)
    out["put_enable_fast_alpr_status"] = put.status_code
    put.raise_for_status()
    after = requests.get(f"{BASE}/api/cameras/{CAMERA_ID}", headers=headers, timeout=20).json()
    out["camera_final_enabled_plugins"] = after.get("enabled_plugins")

    bus = requests.get(f"{BASE}/api/plugins/bus", headers=headers, timeout=20)
    out["plugins_bus_status"] = bus.status_code
    out["plugins_bus_total"] = (bus.json().get("counts") or {}).get("total") if bus.ok else None

    frame = requests.get(f"{BASE}/api/diagnostics/frame-source", headers=headers, timeout=20)
    out["frame_source_status"] = frame.status_code
    workers = (frame.json().get("workers") or {}) if frame.ok else {}
    out["frame_source_alive_workers"] = [cid for cid, w in workers.items() if w.get("alive")]

    catalog = requests.get(f"{BASE}/api/plugins/catalog", headers=headers, timeout=20)
    out["plugins_catalog_status"] = catalog.status_code
    out["plugins_catalog_total"] = catalog.json().get("total") if catalog.ok else None
    out["plugins_catalog_group_count"] = len(catalog.json().get("groups") or []) if catalog.ok else 0

    print(json.dumps(out, ensure_ascii=False, indent=2))
    assert out["login_has_access_token"] is True
    assert "fast-alpr" in out["camera_final_enabled_plugins"]
    assert out["plugins_bus_total"] == 50
    assert out["frame_source_alive_workers"]
    assert out["plugins_catalog_total"] == 50 and out["plugins_catalog_group_count"] > 0


if __name__ == "__main__":
    main()