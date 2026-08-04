#!/usr/bin/env python3
"""Focused backend verification for MG-VMS v0.4 stabilization bug report."""
import json
import os
import sys
import time
from urllib import request, error

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://video-command-6.preview.emergentagent.com").rstrip("/")
EMAIL = os.environ.get("MGVMS_TEST_EMAIL", "admin@mg-vms.com")
PASSWORD = os.environ.get("MGVMS_TEST_PASSWORD", "Admin@2026")
TIMEOUT = 25

results = {"base_url": BASE_URL, "checks": [], "raw": {}}
TOKEN = None


def record(name, ok, detail="", data=None):
    item = {"name": name, "ok": bool(ok), "detail": detail}
    if data is not None:
        item["data"] = data
    results["checks"].append(item)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def http_json(method, path, payload=None, token=None, timeout=TIMEOUT):
    url = BASE_URL + path
    body = None
    # Cloudflare preview can block Python's default urllib user-agent. Use a
    # normal CLI client UA so the test hits the same backend path as curl.
    headers = {"Accept": "application/json", "User-Agent": "curl/8.5.0"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, data=body, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(text) if text else None
            except json.JSONDecodeError:
                data = text[:1000]
            return resp.status, data, dict(resp.headers)
    except error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text) if text else text
        except json.JSONDecodeError:
            data = text[:1000]
        return e.code, data, dict(e.headers)


def main():
    global TOKEN
    # Auth regression
    status, data, _ = http_json("POST", "/api/auth/login", {"email": EMAIL, "password": PASSWORD})
    results["raw"]["login"] = {"status": status, "body_keys": list(data.keys()) if isinstance(data, dict) else type(data).__name__}
    TOKEN = data.get("access_token") if status == 200 and isinstance(data, dict) else None
    record("admin login returns access_token", status == 200 and bool(TOKEN), f"status={status}, token_present={bool(TOKEN)}")
    if not TOKEN:
        results["summary"] = "Cannot continue protected endpoint checks without token"
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 2

    # Plugins bus: 50 entries, all loaded/dispatchable enough, not only built-in fallbacks.
    status, bus, _ = http_json("GET", "/api/plugins/bus", token=TOKEN)
    entries = bus.get("entries", []) if status == 200 and isinstance(bus, dict) else []
    counts = bus.get("counts", {}) if isinstance(bus, dict) else {}
    names = [e.get("name") for e in entries if isinstance(e, dict)]
    state_counts = {}
    for e in entries:
        if isinstance(e, dict):
            state_counts[e.get("state", "?")] = state_counts.get(e.get("state", "?"), 0) + 1
    results["raw"]["plugins_bus"] = {"status": status, "count": len(entries), "counts": counts, "names_sample": names[:10]}
    record("GET /api/plugins/bus has 50 entries", status == 200 and len(entries) == 50 and counts.get("total") == 50, f"status={status}, entries={len(entries)}, counts.total={counts.get('total')}")
    record("plugins bus is not fallback-only", len(set(names)) >= 50 and set(["yolo-detection", "fast-alpr"]).issubset(set(names)), f"unique_names={len(set(names))}, contains_required={set(['yolo-detection','fast-alpr']).issubset(set(names))}")
    record("plugins bus entries are all enabled (not fallback-only)", counts.get("enabled") == 50, f"enabled={counts.get('enabled')}, states={state_counts}")

    # Loader endpoint gives loaded=true for all dynamic plugins and directory.
    status, loader, _ = http_json("GET", "/api/plugins/loader", token=TOKEN)
    loaded = loader.get("loaded", []) if status == 200 and isinstance(loader, dict) else []
    failed = [p for p in loaded if not p.get("loaded") or p.get("error")]
    results["raw"]["plugins_loader"] = {"status": status, "plugins_dir": loader.get("plugins_dir") if isinstance(loader, dict) else None, "count": len(loaded), "failed": failed[:5]}
    record("GET /api/plugins/loader has 50 loaded=true and no errors", status == 200 and len(loaded) == 50 and not failed, f"status={status}, loaded={len(loaded)}, failed={len(failed)}, dir={loader.get('plugins_dir') if isinstance(loader, dict) else None}")

    # Catalog: total=50 available=50 with >=9 groups.
    status, catalog, _ = http_json("GET", "/api/plugins/catalog", token=TOKEN)
    groups = catalog.get("groups", []) if status == 200 and isinstance(catalog, dict) else []
    results["raw"]["plugins_catalog"] = {"status": status, "total": catalog.get("total") if isinstance(catalog, dict) else None, "available": catalog.get("available") if isinstance(catalog, dict) else None, "group_count": len(groups), "groups": [g.get("category") for g in groups[:20]]}
    record("GET /api/plugins/catalog total=50 available=50 groups>=9", status == 200 and catalog.get("total") == 50 and catalog.get("available") == 50 and len(groups) >= 9, f"status={status}, total={catalog.get('total') if isinstance(catalog, dict) else None}, available={catalog.get('available') if isinstance(catalog, dict) else None}, groups={len(groups)}")

    # WSDL diagnostics.
    status, wsdl, _ = http_json("GET", "/api/diagnostics/wsdl", token=TOKEN)
    missing_required = wsdl.get("missing_required") if isinstance(wsdl, dict) else None
    results["raw"]["wsdl"] = {"status": status, "body": wsdl}
    record("GET /api/diagnostics/wsdl ok true with 7 required found", status == 200 and wsdl.get("ok") is True and wsdl.get("found") == 7 and missing_required == [], f"status={status}, ok={wsdl.get('ok') if isinstance(wsdl, dict) else None}, found={wsdl.get('found') if isinstance(wsdl, dict) else None}, missing_required={missing_required}")

    # Pipeline metrics before config update: runtime.bytetrack + GPU fields.
    status, metrics_before, _ = http_json("GET", "/api/diagnostics/pipeline-metrics", token=TOKEN)
    runtime = metrics_before.get("runtime", {}) if status == 200 and isinstance(metrics_before, dict) else {}
    bt = runtime.get("bytetrack", {}) if isinstance(runtime, dict) else {}
    gpu = runtime.get("gpu", {}) if isinstance(runtime, dict) else {}
    results["raw"]["pipeline_before"] = {"status": status, "runtime": runtime}
    gpu_fields_ok = all(k in gpu for k in ("torch", "cuda_available", "cuda_version", "device_name"))
    record("GET /api/diagnostics/pipeline-metrics exposes runtime.bytetrack enabled", status == 200 and bt.get("enabled") is True and all(k in bt for k in ("track_thresh", "match_thresh", "track_buffer")), f"status={status}, bytetrack={bt}")
    record("GET /api/diagnostics/pipeline-metrics exposes runtime.gpu torch/cuda fields", status == 200 and gpu_fields_ok, f"gpu={gpu}")

    # AI health: regression for sys.get_int_max_str_digits/CUDA incompatibility should not surface.
    status, ai_health, _ = http_json("GET", "/api/diagnostics/ai-health", token=TOKEN)
    results["raw"]["ai_health"] = {"status": status, "body": ai_health}
    ai_text = json.dumps(ai_health, ensure_ascii=False) if isinstance(ai_health, dict) else str(ai_health)
    ai_ok = (
        status == 200 and isinstance(ai_health, dict)
        and ai_health.get("torch_available") is True
        and ai_health.get("torch_error") in (None, "")
        and ai_health.get("last_cycle_error") in (None, "")
        and "get_int_max_str_digits" not in ai_text
    )
    record("GET /api/diagnostics/ai-health has no sys.get_int_max_str_digits/CUDA crash", ai_ok, f"status={status}, torch={ai_health.get('torch_version') if isinstance(ai_health, dict) else None}, yolo_loaded={ai_health.get('yolo_loaded') if isinstance(ai_health, dict) else None}, alpr_loaded={ai_health.get('alpr_loaded') if isinstance(ai_health, dict) else None}, last_cycle_error={ai_health.get('last_cycle_error') if isinstance(ai_health, dict) else None}")

    # Tracking config sync: save original, PUT enabled true track_thresh 0.3, immediately GET metrics.
    status, orig_cfg, _ = http_json("GET", "/api/plugins/tracking/config", token=TOKEN)
    results["raw"]["tracking_config_before"] = {"status": status, "body": orig_cfg}
    new_cfg = dict(orig_cfg) if status == 200 and isinstance(orig_cfg, dict) else {
        "enabled": True, "track_thresh": 0.25, "match_thresh": 0.85, "track_buffer": 60,
        "min_box_area": 100, "id_persist_seconds": 120,
    }
    new_cfg.update({"enabled": True, "track_thresh": 0.3})
    status_put, put_body, _ = http_json("PUT", "/api/plugins/tracking/config", new_cfg, token=TOKEN)
    time.sleep(0.25)
    status_after, metrics_after, _ = http_json("GET", "/api/diagnostics/pipeline-metrics", token=TOKEN)
    bt_after = (((metrics_after or {}).get("runtime") or {}).get("bytetrack") or {}) if isinstance(metrics_after, dict) else {}
    results["raw"]["tracking_update"] = {"put_status": status_put, "put_body": put_body, "get_status": status_after, "bytetrack_after": bt_after}
    record("PUT /api/plugins/tracking/config syncs runtime immediately", status_put == 200 and status_after == 200 and bt_after.get("enabled") is True and abs(float(bt_after.get("track_thresh", -1)) - 0.3) < 1e-9, f"put_status={status_put}, get_status={status_after}, runtime.bytetrack={bt_after}")

    # Frame source non-regression: demo-cam-002 worker alive.
    status, frame_src, _ = http_json("GET", "/api/diagnostics/frame-source", token=TOKEN)
    workers = frame_src.get("workers", {}) if status == 200 and isinstance(frame_src, dict) else {}
    worker = workers.get("demo-cam-002") if isinstance(workers, dict) else None
    results["raw"]["frame_source"] = {"status": status, "demo-cam-002": worker, "worker_keys": list(workers.keys()) if isinstance(workers, dict) else None}
    record("GET /api/diagnostics/frame-source demo-cam-002 worker alive", status == 200 and isinstance(worker, dict) and worker.get("alive") is True, f"status={status}, demo-cam-002={worker}")

    ok_count = sum(1 for c in results["checks"] if c["ok"])
    total = len(results["checks"])
    results["summary"] = f"{ok_count}/{total} checks passed"
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if ok_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
