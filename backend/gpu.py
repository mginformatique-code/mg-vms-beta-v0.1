"""MG-VMS — Détection et supervision GPU multi-vendor.

Compatible NVIDIA (via `pynvml` / `nvidia-ml-py`) + fallback pour AMD/Intel/Apple
via les runtimes détectés (torch.cuda / onnxruntime / OpenCV CUDA).

Fonctions publiques :
- `gpu_summary()`    → dict compact pour le header web (poll 5s)
- `gpu_full_info()`  → dict détaillé pour la page GPU (nom, driver, VRAM, temp, power, %util, runtimes...)
- `is_gpu_active_for_pipeline()` → bool : le pipeline IA utilise-t-il vraiment le GPU ?

100% no-crash : chaque probe est isolé dans un `try/except` — si `pynvml.NVMLError_DriverNotLoaded`
survient (pas de pilote NVIDIA), on répond `available=False` sans faire tomber le backend.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from functools import lru_cache
from typing import Optional

logger = logging.getLogger("gpu")

# Cache des probes lourds (torch/onnxruntime/cv2) — un seul appel par process
_RUNTIME_CACHE: dict = {}
# Cache court des métriques temps réel (poll léger toutes les ~2 s)
_METRICS_CACHE: dict = {"t": 0.0, "data": None}
_METRICS_TTL = 2.0  # secondes


# ============================================================================
# Détection des runtimes CUDA/TensorRT/ONNX/OpenCV
# ============================================================================
def _runtime_pytorch() -> dict:
    """Vérifie si torch.cuda est disponible et retourne les versions."""
    if "pytorch" in _RUNTIME_CACHE:
        return _RUNTIME_CACHE["pytorch"]
    info: dict = {"available": False, "version": None, "cuda_version": None,
                    "device_count": 0, "device_names": []}
    try:
        import torch
        info["version"] = torch.__version__
        info["cuda_version"] = getattr(torch.version, "cuda", None)
        info["available"] = bool(torch.cuda.is_available())
        if info["available"]:
            info["device_count"] = torch.cuda.device_count()
            info["device_names"] = [torch.cuda.get_device_name(i) for i in range(info["device_count"])]
    except Exception as e:
        info["error"] = str(e)[:200]
    _RUNTIME_CACHE["pytorch"] = info
    return info


def _runtime_onnx() -> dict:
    """Vérifie si onnxruntime-gpu est disponible + providers actifs."""
    if "onnx" in _RUNTIME_CACHE:
        return _RUNTIME_CACHE["onnx"]
    info: dict = {"available": False, "version": None, "providers": [], "gpu_provider": None}
    try:
        import onnxruntime as ort
        info["version"] = ort.__version__
        info["providers"] = list(ort.get_available_providers())
        for p in ("CUDAExecutionProvider", "TensorrtExecutionProvider",
                    "ROCMExecutionProvider", "CoreMLExecutionProvider", "DmlExecutionProvider"):
            if p in info["providers"]:
                info["available"] = True
                info["gpu_provider"] = p
                break
    except Exception as e:
        info["error"] = str(e)[:200]
    _RUNTIME_CACHE["onnx"] = info
    return info


def _runtime_opencv() -> dict:
    """OpenCV CUDA (rare — dépend d'un build custom)."""
    if "cv2" in _RUNTIME_CACHE:
        return _RUNTIME_CACHE["cv2"]
    info: dict = {"available": False, "version": None, "cuda_devices": 0}
    try:
        import cv2
        info["version"] = cv2.__version__
        cnt = 0
        try:
            cnt = cv2.cuda.getCudaEnabledDeviceCount()
        except Exception:
            cnt = 0
        info["cuda_devices"] = cnt
        info["available"] = cnt > 0
    except Exception as e:
        info["error"] = str(e)[:200]
    _RUNTIME_CACHE["cv2"] = info
    return info


def _runtime_tensorrt() -> dict:
    """TensorRT (import ou binaire trtexec)."""
    if "trt" in _RUNTIME_CACHE:
        return _RUNTIME_CACHE["trt"]
    info: dict = {"available": False, "version": None, "source": None}
    try:
        import tensorrt as trt
        info["version"] = trt.__version__
        info["available"] = True
        info["source"] = "python"
    except Exception:
        # Fallback : binaire trtexec présent dans le PATH ?
        exe = shutil.which("trtexec")
        if exe:
            info["available"] = True
            info["source"] = "binary"
            try:
                r = subprocess.run([exe, "--help"], capture_output=True, timeout=3, text=True)
                # trtexec écrit sa version en tête
                for ln in (r.stdout + r.stderr).splitlines():
                    if "TensorRT" in ln:
                        info["version"] = ln.strip()[:80]
                        break
            except Exception:
                pass
    _RUNTIME_CACHE["trt"] = info
    return info


# ============================================================================
# Détection NVIDIA via pynvml (nvidia-ml-py 13.x)
# ============================================================================
_NVML_INITIALIZED = False
_NVML_ERROR: Optional[str] = None


def _init_nvml() -> bool:
    global _NVML_INITIALIZED, _NVML_ERROR
    if _NVML_INITIALIZED:
        return True
    if _NVML_ERROR is not None:
        return False
    try:
        import pynvml
        pynvml.nvmlInit()
        _NVML_INITIALIZED = True
        return True
    except Exception as e:
        _NVML_ERROR = str(e)[:200]
        logger.info("NVML non disponible : %s", _NVML_ERROR)
        return False


def _nvml_devices() -> list[dict]:
    """Retourne la liste des GPU NVIDIA détectés via NVML."""
    if not _init_nvml():
        return []
    import pynvml
    out: list[dict] = []
    try:
        cnt = pynvml.nvmlDeviceGetCount()
    except Exception:
        return []
    for i in range(cnt):
        d: dict = {"index": i}
        try:
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            d["name"] = _nvml_str(pynvml.nvmlDeviceGetName(h))
            try:
                d["uuid"] = _nvml_str(pynvml.nvmlDeviceGetUUID(h))
            except Exception:
                pass
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                d["vram_total_mb"] = int(mem.total / (1024 * 1024))
                d["vram_used_mb"] = int(mem.used / (1024 * 1024))
                d["vram_free_mb"] = int(mem.free / (1024 * 1024))
                d["vram_util_pct"] = round((mem.used / mem.total) * 100, 1) if mem.total else 0
            except Exception:
                pass
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                d["gpu_util_pct"] = int(util.gpu)
                d["memory_bus_util_pct"] = int(util.memory)
            except Exception:
                pass
            try:
                # Encoder / Decoder utilisation (crucial pour VMS)
                enc = pynvml.nvmlDeviceGetEncoderUtilization(h)
                d["encoder_util_pct"] = int(enc[0])
                dec = pynvml.nvmlDeviceGetDecoderUtilization(h)
                d["decoder_util_pct"] = int(dec[0])
            except Exception:
                pass
            try:
                d["temperature_c"] = int(pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU))
            except Exception:
                pass
            try:
                d["power_w"] = round(pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0, 1)
                d["power_limit_w"] = round(pynvml.nvmlDeviceGetEnforcedPowerLimitConstraints(h)[1] / 1000.0, 1) \
                    if hasattr(pynvml, "nvmlDeviceGetEnforcedPowerLimitConstraints") else None
            except Exception:
                try:
                    d["power_w"] = round(pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0, 1)
                except Exception:
                    pass
            try:
                d["fan_pct"] = int(pynvml.nvmlDeviceGetFanSpeed(h))
            except Exception:
                pass
            try:
                d["clock_graphics_mhz"] = int(pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_GRAPHICS))
                d["clock_memory_mhz"] = int(pynvml.nvmlDeviceGetClockInfo(h, pynvml.NVML_CLOCK_MEM))
            except Exception:
                pass
            try:
                pcap = pynvml.nvmlDeviceGetCudaComputeCapability(h)
                d["cuda_compute_capability"] = f"{pcap[0]}.{pcap[1]}"
            except Exception:
                pass
            try:
                d["persistence_mode"] = bool(pynvml.nvmlDeviceGetPersistenceMode(h))
            except Exception:
                pass
        except Exception as e:
            d["error"] = str(e)[:200]
        out.append(d)
    return out


def _nvml_str(v) -> str:
    """Certaines versions de NVML renvoient des bytes, d'autres des str."""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return str(v)


def _nvml_driver() -> dict:
    if not _init_nvml():
        return {}
    import pynvml
    d: dict = {}
    try:
        d["driver_version"] = _nvml_str(pynvml.nvmlSystemGetDriverVersion())
    except Exception:
        pass
    try:
        d["nvml_version"] = _nvml_str(pynvml.nvmlSystemGetNVMLVersion())
    except Exception:
        pass
    try:
        d["cuda_driver_version"] = pynvml.nvmlSystemGetCudaDriverVersion()
    except Exception:
        pass
    return d


# ============================================================================
# API publique
# ============================================================================
def gpu_summary() -> dict:
    """Snapshot LIGHT pour le header web (poll 5s). Mémoïsé 2 s."""
    now = time.time()
    if _METRICS_CACHE["data"] is not None and (now - _METRICS_CACHE["t"]) < _METRICS_TTL:
        return _METRICS_CACHE["data"]
    devices = _nvml_devices()
    if devices:
        # Agrège si multi-GPU (rare) — prend max util + total VRAM
        util = max((d.get("gpu_util_pct") or 0) for d in devices)
        total = sum((d.get("vram_total_mb") or 0) for d in devices)
        used = sum((d.get("vram_used_mb") or 0) for d in devices)
        temp = max((d.get("temperature_c") or 0) for d in devices)
        name = devices[0].get("name", "GPU")
        summary = {
            "available": True,
            "vendor": "NVIDIA",
            "name": name,
            "count": len(devices),
            "gpu_util_pct": util,
            "vram_used_mb": used,
            "vram_total_mb": total,
            "vram_util_pct": round((used / total) * 100, 1) if total else 0,
            "temperature_c": temp,
        }
    else:
        # Aucun GPU NVIDIA — signale explicitement le mode CPU
        summary = {
            "available": False,
            "vendor": None,
            "name": None,
            "count": 0,
            "gpu_util_pct": 0,
            "vram_used_mb": 0,
            "vram_total_mb": 0,
            "vram_util_pct": 0,
            "temperature_c": 0,
            "error": _NVML_ERROR or "Aucun GPU NVIDIA détecté",
        }
    _METRICS_CACHE["t"] = now
    _METRICS_CACHE["data"] = summary
    return summary


def gpu_full_info() -> dict:
    """Rapport complet pour la page /gpu — runtimes + GPU + pipeline actif."""
    driver = _nvml_driver()
    devices = _nvml_devices()
    pt = _runtime_pytorch()
    ox = _runtime_onnx()
    cv = _runtime_opencv()
    trt = _runtime_tensorrt()
    # Le pipeline IA est-il vraiment sur GPU ?
    pipeline_gpu = bool(pt.get("available"))  # YOLO Ultralytics utilise torch.cuda si dispo
    return {
        "available": bool(devices),
        "vendor": "NVIDIA" if devices else None,
        "driver": driver,
        "devices": devices,
        "runtimes": {
            "pytorch": pt,
            "tensorrt": trt,
            "onnx_runtime": ox,
            "opencv_cuda": cv,
        },
        "pipeline": {
            "yolo_uses_gpu": pipeline_gpu,
            "detection_backend": "torch.cuda" if pipeline_gpu else "torch.cpu",
        },
        "diagnostic": {
            "nvml_error": _NVML_ERROR,
            "nvidia_smi_available": shutil.which("nvidia-smi") is not None,
        },
    }


def is_gpu_active_for_pipeline() -> bool:
    """Le pipeline IA (YOLO/InsightFace) utilise-t-il réellement le GPU ?"""
    return bool(_runtime_pytorch().get("available"))
