#!/usr/bin/env python3
"""Focused verification for Phase 3 GPU + ANPR benchmark contract."""
import json
import os
import subprocess
import sys
from pathlib import Path

import requests


ROOT = Path("/app")
BACKEND = ROOT / "backend"
FRONTEND_ENV = ROOT / "frontend" / ".env"
REQ = BACKEND / "requirements.txt"
GPU_PY = BACKEND / "gpu.py"


def frontend_base_url():
    for line in FRONTEND_ENV.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    return "http://localhost:8001"


BASE = os.environ.get("BASE_URL", frontend_base_url()).rstrip("/")
API = BASE + "/api"


def assert_keys(obj, keys, label):
    missing = [k for k in keys if k not in obj]
    assert not missing, f"{label} missing keys: {missing}; got {sorted(obj.keys())}"


def main():
    results = {"base_url": BASE, "checks": []}

    def record(name, ok, detail=""):
        results["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        print(("PASS" if ok else "FAIL") + f" {name}: {detail}")

    # Static contract checks
    req_text = REQ.read_text(errors="ignore")
    record("requirements_nvidia_ml_py", "nvidia-ml-py==13.610.43" in req_text, "nvidia-ml-py==13.610.43 present")

    gpu_text = GPU_PY.read_text(errors="ignore")
    for needle in ["pynvml.NVML_TEMPERATURE_GPU", "nvmlDeviceGetEncoderUtilization", "nvmlDeviceGetDecoderUtilization", "bytes", "decode"]:
        record(f"gpu_py_contains_{needle}", needle in gpu_text, needle)
    record("gpu_py_nvml_device_usage_count", gpu_text.count("nvmlDevice") >= 8, f"count={gpu_text.count('nvmlDevice')}")

    # Direct module no-GPU fallback check in a subprocess, from backend cwd.
    module_code = (
        "from gpu import gpu_summary, gpu_full_info; import json; "
        "s=gpu_summary(); f=gpu_full_info(); "
        "assert s['available'] is False, s; "
        "assert f['pipeline']['detection_backend'] == 'torch.cpu', f['pipeline']; "
        "print(json.dumps({'summary': s, 'pipeline': f['pipeline'], 'diagnostic': f['diagnostic']}, ensure_ascii=False))"
    )
    proc = subprocess.run([sys.executable, "-c", module_code], cwd=str(BACKEND), capture_output=True, text=True, timeout=60)
    record("gpu_module_no_crash_no_gpu", proc.returncode == 0, (proc.stdout or proc.stderr)[-1000:])

    # Login and API contract checks.
    sess = requests.Session()
    login = sess.post(f"{API}/auth/login", json={"email": "admin@mg-vms.com", "password": "Admin@2026"}, timeout=30)
    record("admin_login", login.status_code == 200, f"status={login.status_code} body={login.text[:300]}")
    login.raise_for_status()
    access = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}

    r = sess.get(f"{API}/system/gpu/summary", headers=headers, timeout=30)
    record("gpu_summary_status_200", r.status_code == 200, f"status={r.status_code} body={r.text[:500]}")
    r.raise_for_status()
    summary = r.json()
    assert_keys(summary, ["available", "vendor", "name", "count", "gpu_util_pct", "vram_used_mb", "vram_total_mb", "vram_util_pct", "temperature_c"], "gpu summary")
    record("gpu_summary_contract_keys", True, json.dumps(summary, ensure_ascii=False)[:700])
    record("gpu_summary_no_gpu_fallback", summary.get("available") is False and bool(summary.get("error")), f"available={summary.get('available')} error={summary.get('error')}")

    r = sess.get(f"{API}/system/gpu", headers=headers, timeout=60)
    record("gpu_full_status_200", r.status_code == 200, f"status={r.status_code} body={r.text[:500]}")
    r.raise_for_status()
    full = r.json()
    assert_keys(full, ["available", "vendor", "driver", "devices", "runtimes", "pipeline", "diagnostic"], "gpu full")
    assert_keys(full["runtimes"], ["pytorch", "tensorrt", "onnx_runtime", "opencv_cuda"], "gpu runtimes")
    for key in ["pytorch", "tensorrt", "onnx_runtime", "opencv_cuda"]:
        assert_keys(full["runtimes"][key], ["available", "version"], f"runtime {key}")
    assert_keys(full["pipeline"], ["yolo_uses_gpu", "detection_backend"], "pipeline")
    assert_keys(full["diagnostic"], ["nvml_error", "nvidia_smi_available"], "diagnostic")
    record("gpu_full_contract_keys", True, json.dumps(full, ensure_ascii=False)[:1000])
    record("gpu_full_cpu_pipeline", full["pipeline"].get("detection_backend") == "torch.cpu", str(full["pipeline"]))

    r = sess.get(f"{API}/dashboard/stats", headers=headers, timeout=30)
    record("dashboard_stats_has_gpu", r.status_code == 200 and "gpu" in r.json().get("system", {}), f"status={r.status_code} gpu={r.json().get('system', {}).get('gpu') if r.status_code == 200 else r.text[:300]}")

    # Validation bounds: expected 400 for iterations outside 1..30.
    for iterations in [0, 50]:
        r = sess.post(f"{API}/system/anpr-benchmark", params={"iterations": iterations}, headers=headers, timeout=30)
        record(f"anpr_benchmark_validation_{iterations}", r.status_code == 400, f"status={r.status_code} body={r.text[:300]}")

    # Main benchmark contract, with default camera selection.
    r = sess.post(f"{API}/system/anpr-benchmark", params={"iterations": 3}, headers=headers, timeout=180)
    record("anpr_benchmark_iterations_3_status_200", r.status_code == 200, f"status={r.status_code} body={r.text[:1000]}")
    r.raise_for_status()
    bench = r.json()
    bench_keys = ["camera_id", "iterations", "resolution_analyzed", "avg_total_ms", "avg_yolo_ms", "avg_alpr_ms", "estimated_fps", "plates_detected_total", "plates_ocr_success", "plates_ocr_failed", "ocr_success_rate", "avg_detections_per_frame", "gpu_active", "torch_backend", "torch_version", "cuda_version", "yolo_model", "alpr_model", "samples", "run_at"]
    assert_keys(bench, bench_keys, "anpr benchmark")
    record("anpr_benchmark_contract_keys", True, json.dumps(bench, ensure_ascii=False)[:1200])
    record("anpr_benchmark_cpu_backend", bench.get("torch_backend") in ["cpu", "cuda"] and isinstance(bench.get("gpu_active"), bool), f"torch_backend={bench.get('torch_backend')} gpu_active={bench.get('gpu_active')}")
    record("anpr_benchmark_sample_count", len(bench.get("samples", [])) == 3, f"samples={len(bench.get('samples', []))}")

    ok = all(c["ok"] for c in results["checks"])
    results["overall_ok"] = ok
    out = Path("/app/test_reports/gpu_anpr_backend_verification_results.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())