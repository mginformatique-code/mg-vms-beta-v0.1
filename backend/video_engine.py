"""MG-VMS — Moteur vidéo intelligent : auto-détection + config + fabrique de pipelines.

Choisit automatiquement le meilleur pipeline (GPU NVDEC / CPU) et le meilleur mode
d'aperçu (WebRTC / MJPEG / MSE) selon les capacités matérielles réelles, tout en
laissant l'administrateur forcer un mode via l'UI.

Sources d'accélération :
- NVIDIA NVDEC (h264_cuvid / hevc_cuvid) + `scale_cuda` + `colorspace_cuda`
- NVENC pour tout ré-encodage nécessaire (h264_nvenc / hevc_nvenc)
- Détection via `ffmpeg -hwaccels`, `ffmpeg -codecs`, et `nvidia-ml-py`
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Optional

from database import db

logger = logging.getLogger("video_engine")

# ============================================================================
# Détection des capacités FFmpeg / GPU (mémoïsée pour éviter les subprocess répétés)
# ============================================================================
@lru_cache(maxsize=1)
def _ffmpeg_capabilities() -> dict:
    """Sonde ffmpeg pour détecter hwaccels + décodeurs + encodeurs + filtres CUDA."""
    caps: dict = {
        "hwaccels": [], "decoders_gpu": [], "encoders_gpu": [], "filters_cuda": [],
        "ffmpeg_available": False, "ffmpeg_version": "",
    }
    exe = shutil.which("ffmpeg")
    if not exe:
        return caps
    caps["ffmpeg_available"] = True
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, timeout=5, text=True)
        first = (r.stdout or r.stderr).splitlines()[0] if (r.stdout or r.stderr) else ""
        caps["ffmpeg_version"] = first.strip()[:120]
    except Exception:
        pass
    try:
        r = subprocess.run([exe, "-hide_banner", "-hwaccels"], capture_output=True, timeout=5, text=True)
        caps["hwaccels"] = [ln.strip() for ln in (r.stdout or "").splitlines()[1:] if ln.strip()]
    except Exception:
        pass
    # Decoders GPU (cuvid)
    try:
        r = subprocess.run([exe, "-hide_banner", "-decoders"], capture_output=True, timeout=6, text=True)
        for ln in (r.stdout or "").splitlines():
            m = re.search(r"\s(h264_cuvid|hevc_cuvid|av1_cuvid|mjpeg_cuvid|mpeg4_cuvid|vp9_cuvid|vp8_cuvid)\s", ln)
            if m:
                caps["decoders_gpu"].append(m.group(1))
    except Exception:
        pass
    # Encoders GPU (nvenc)
    try:
        r = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, timeout=6, text=True)
        for ln in (r.stdout or "").splitlines():
            m = re.search(r"\s(h264_nvenc|hevc_nvenc|av1_nvenc)\s", ln)
            if m:
                caps["encoders_gpu"].append(m.group(1))
    except Exception:
        pass
    # Filtres CUDA
    try:
        r = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True, timeout=6, text=True)
        for ln in (r.stdout or "").splitlines():
            m = re.search(r"\s(scale_cuda|colorspace_cuda|hwupload_cuda|overlay_cuda|thumbnail_cuda|yadif_cuda|scale_npp)\s", ln)
            if m:
                caps["filters_cuda"].append(m.group(1))
    except Exception:
        pass
    return caps


async def has_cuda_pipeline() -> bool:
    """Le pipeline hardware-accel CUDA (NVDEC + scale_cuda) est-il utilisable ?
    Nécessite `cuda` dans hwaccels + au moins h264_cuvid + scale_cuda.
    """
    caps = _ffmpeg_capabilities()
    # v3.29 · Croise avec la présence effective d'un GPU NVIDIA — vit dans le
    # conteneur pipeline depuis la Phase 3, lu via le snapshot Redis plutôt
    # qu'un import direct de gpu.py (qui sonderait le conteneur API, sans GPU).
    try:
        from pipeline_snapshot import get_snapshot
        snap = await get_snapshot()
        gpu_ok = bool((snap or {}).get("gpu_summary", {}).get("available"))
    except Exception:
        gpu_ok = False
    return (gpu_ok
            and "cuda" in caps["hwaccels"]
            and any(d in caps["decoders_gpu"] for d in ("h264_cuvid", "hevc_cuvid"))
            and "scale_cuda" in caps["filters_cuda"])


# ============================================================================
# Configuration persistée (Mongo) — modes forcés par l'admin
# ============================================================================
DEFAULT_CONFIG: dict = {
    "pipeline_mode": "auto",   # auto | gpu | cpu | direct
    "preview_mode": "auto",    # auto | webrtc | mjpeg | mse
    "ai_pipeline": "auto",     # auto | gpu | cpu
    "recorder_mode": "auto",   # auto | copy | reencode
    # v1.0-rc4.5 · Phase 1 · Root cause Go2RTC (transcoding MJPEG CPU-heavy) :
    # La variante _hd sert d'aperçu navigateur ; transcoder à 4K/1080p natif
    # en MJPEG dans le conteneur go2rtc SANS hwaccel (GO2RTC_FFMPEG_CUDA=0 par
    # défaut) sature le CPU et produit lag/artefacts. 1280×native ratio est un
    # compromis excellent (qualité perceptible identique, coût CPU ÷ 3-4).
    # L'admin peut toujours forcer 0 (résolution native) via /pipeline UI.
    "hd_preview_width": 1280,
    "sd_preview_width": 640,
    "sd_preview_fps": 15,
    "low_latency": True,
}


async def get_config() -> dict:
    """Retourne la config vidéo courante (fusion défauts + persistée)."""
    doc = await db.system_config.find_one({"key": "video_engine"}, {"_id": 0})
    cfg = dict(DEFAULT_CONFIG)
    if doc and "value" in doc:
        cfg.update(doc["value"] or {})
    return cfg


async def set_config(new_cfg: dict) -> dict:
    """Met à jour la config (upsert)."""
    allowed = set(DEFAULT_CONFIG.keys())
    clean = {k: v for k, v in new_cfg.items() if k in allowed}
    current = await get_config()
    current.update(clean)
    await db.system_config.update_one(
        {"key": "video_engine"},
        {"$set": {"key": "video_engine", "value": current}},
        upsert=True,
    )
    return current


# ============================================================================
# Résolution du pipeline effectif pour une caméra
# ============================================================================
def _codec_to_cuvid(codec: str) -> Optional[str]:
    """Retourne le décodeur cuvid pour un codec source, ou None."""
    if not codec:
        return None
    c = codec.upper().replace(".", "")
    return {"H264": "h264_cuvid", "AVC": "h264_cuvid",
             "H265": "hevc_cuvid", "HEVC": "hevc_cuvid",
             "AV1": "av1_cuvid"}.get(c)


async def resolve_pipeline(cam: dict) -> dict:
    """Détermine le pipeline effectif pour la caméra courante.

    Retourne :
      - `mode` : "gpu" ou "cpu"
      - `decoder` : "h264_cuvid" / "hevc_cuvid" / "software"
      - `preview` : "webrtc" / "mjpeg" / "mse"
      - `recorder` : "copy" / "reencode-cpu" / "reencode-gpu"
      - `ai` : "gpu" / "cpu"
      - `mjpeg_filter_hd` / `mjpeg_filter_sd` : chaînes ffmpeg optimisées
      - `raison_gpu` / `raison_cpu` : explique le choix (pour la page /pipeline)
    """
    cfg = await get_config()
    caps = _ffmpeg_capabilities()
    cuda_ok = await has_cuda_pipeline()

    # 1) Pipeline global (GPU ou CPU)
    forced_mode = cfg["pipeline_mode"]
    if forced_mode == "gpu":
        mode = "gpu" if cuda_ok else "cpu"
        why = "GPU forcé (admin)" if cuda_ok else "GPU demandé mais indisponible — fallback CPU"
    elif forced_mode == "cpu":
        mode = "cpu"
        why = "CPU forcé (admin)"
    elif forced_mode == "direct":
        mode = "direct"  # géré par WebRTC pass-through
        why = "Mode direct (WebRTC pass-through sans transcodage)"
    else:  # auto
        mode = "gpu" if cuda_ok else "cpu"
        why = ("Auto → GPU (CUDA + NVDEC + scale_cuda détectés)"
               if cuda_ok else "Auto → CPU (pas de GPU NVIDIA utilisable)")

    # 2) Décodeur pour cette caméra
    codec = (cam.get("codec") or "H264").upper()
    cuvid = _codec_to_cuvid(codec)
    if mode == "gpu" and cuvid and cuvid in caps["decoders_gpu"]:
        decoder = cuvid
    else:
        decoder = "software"

    # 3) Prévisualisation
    forced_preview = cfg["preview_mode"]
    if forced_preview == "webrtc":
        preview = "webrtc"
    elif forced_preview == "mjpeg":
        preview = "mjpeg"
    elif forced_preview == "mse":
        preview = "mse"
    else:  # auto
        # WebRTC est préféré pour codec H.264 (support natif navigateur) sans transcodage
        preview = "webrtc" if codec in ("H264", "AVC") else "mjpeg"

    # 4) Recorder
    forced_rec = cfg["recorder_mode"]
    if forced_rec == "copy":
        recorder = "copy"
    elif forced_rec == "reencode":
        recorder = "reencode-gpu" if mode == "gpu" and "h264_nvenc" in caps["encoders_gpu"] else "reencode-cpu"
    else:  # auto
        recorder = "copy" if codec in ("H264", "H265", "HEVC") else \
                   ("reencode-gpu" if mode == "gpu" and "h264_nvenc" in caps["encoders_gpu"] else "reencode-cpu")

    # 5) IA
    forced_ai = cfg["ai_pipeline"]
    if forced_ai == "gpu":
        ai = "gpu" if cuda_ok else "cpu"
    elif forced_ai == "cpu":
        ai = "cpu"
    else:
        # v3.29 · is_gpu_active_for_pipeline() sonde torch.cuda LOCAL — vit
        # dans le conteneur pipeline depuis la Phase 3. Même calcul déjà
        # publié dans le snapshot (gpu_full_info.pipeline.yolo_uses_gpu).
        try:
            from pipeline_snapshot import get_snapshot
            snap = await get_snapshot()
            ai = "gpu" if (snap or {}).get("gpu_full_info", {}).get("pipeline", {}).get("yolo_uses_gpu") else "cpu"
        except Exception:
            ai = "cpu"

    # 6) Chaîne ffmpeg pour les variantes MJPEG (utilisées par register_camera_stream)
    # NB : go2rtc accepte des paramètres ffmpeg custom via query-string. Format :
    #   ffmpeg:{name}#video=mjpeg#hardware=cuda#width=640
    # ⚠ CRITIQUE : ces filtres sont exécutés par le ffmpeg DU CONTENEUR GO2RTC, pas
    # par le backend. Le conteneur go2rtc n'a en général NI runtime nvidia NI ffmpeg
    # compilé CUDA → `#hardware=cuda` fait échouer le transcodage MJPEG (aperçu noir,
    # frame.jpeg KO, statuts qui flappent). On n'émet ce flag QUE si l'admin a
    # explicitement déclaré GO2RTC_FFMPEG_CUDA=1 (go2rtc avec GPU passthrough).
    # `low_latency` : ajoute `#low_latency` (flag reconnu par go2rtc)
    ll = "#low_latency" if cfg["low_latency"] else ""
    go2rtc_cuda = os.environ.get("GO2RTC_FFMPEG_CUDA", "0") == "1"
    hw = "#hardware=cuda" if (decoder != "software" and go2rtc_cuda) else ""
    width_hd = int(cfg["hd_preview_width"] or 0)
    width_sd = int(cfg["sd_preview_width"] or 640)
    hd_filter = f"video=mjpeg{hw}"
    if width_hd > 0:
        hd_filter += f"#width={width_hd}"
    hd_filter += ll
    sd_filter = f"video=mjpeg{hw}#width={width_sd}{ll}"

    return {
        "mode": mode,
        "reason": why,
        "decoder": decoder,
        "preview": preview,
        "recorder": recorder,
        "ai": ai,
        "codec": codec,
        "cuda_available": cuda_ok,
        "mjpeg_filter_hd": hd_filter,
        "mjpeg_filter_sd": sd_filter,
        "ffmpeg_version": caps["ffmpeg_version"],
        "hwaccels": caps["hwaccels"],
        "decoders_gpu": caps["decoders_gpu"],
        "encoders_gpu": caps["encoders_gpu"],
        "filters_cuda": caps["filters_cuda"],
    }


# ============================================================================
# Rapport global d'état
# ============================================================================
async def engine_status() -> dict:
    """Rapport global du moteur vidéo pour la page /pipeline."""
    caps = _ffmpeg_capabilities()
    cfg = await get_config()
    cuda_ok = await has_cuda_pipeline()
    # Résout le pipeline effectif pour chaque caméra
    cams = await db.cameras.find({}, {"_id": 0}).to_list(500)
    per_camera = []
    for cam in cams:
        try:
            pipe = await resolve_pipeline(cam)
        except Exception as e:
            pipe = {"error": str(e)[:200]}
        per_camera.append({
            "id": cam["id"],
            "name": cam.get("name", ""),
            "site_name": cam.get("site_name", ""),
            "status": cam.get("status"),
            "codec": cam.get("codec"),
            "resolution": cam.get("resolution"),
            "fps": cam.get("fps"),
            "pipeline": pipe,
        })
    return {
        "config": cfg,
        "capabilities": {
            "ffmpeg_available": caps["ffmpeg_available"],
            "ffmpeg_version": caps["ffmpeg_version"],
            "hwaccels": caps["hwaccels"],
            "decoders_gpu": caps["decoders_gpu"],
            "encoders_gpu": caps["encoders_gpu"],
            "filters_cuda": caps["filters_cuda"],
            "cuda_pipeline_ready": cuda_ok,
        },
        "cameras": per_camera,
    }
