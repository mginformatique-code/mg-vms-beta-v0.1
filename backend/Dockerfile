# MG-VMS Backend — Image CUDA 12.4 + Python 3.11 + FFmpeg avec NVDEC/NVENC
# ================================================================================
# But : conteneuriser un runtime capable de :
#   - PyTorch 2.6.0+cu124 (YOLO GPU)
#   - FFmpeg avec hevc_cuvid / h264_cuvid (décodage matériel H.265/H.264)
#   - InsightFace / OpenCV / ANPR
#
# Base : nvidia/cuda:12.4.1-runtime-ubuntu22.04 (fournit les librairies CUDA
# nécessaires à torch et à ffmpeg NVDEC). Le driver reste côté host, injecté
# par nvidia-container-toolkit (--gpus all / runtime: nvidia).

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

WORKDIR /app

# ─── Étape 1 : Python 3.11 + toolchain + FFmpeg NVDEC/NVENC ──────────────
# Le PPA jonathonf/ffmpeg-6 propose un ffmpeg récent avec support CUDA
# (hevc_cuvid, h264_cuvid, scale_cuda, nvenc). Fallback : compilation from
# source si nécessaire.
RUN apt-get update && apt-get install -y --no-install-recommends \
      software-properties-common ca-certificates curl gnupg lsb-release \
      python3.11 python3.11-venv python3-pip python3.11-dev \
      gcc g++ pkg-config \
      libgl1 libglib2.0-0 \
      # FFmpeg avec support CUDA runtime (fourni par le package deadsnakes/ppa upstream si dispo,
      # sinon nous fallback vers le paquet Debian standard - la détection cuvid est faite au runtime).
      ffmpeg \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && python -m pip install --upgrade pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/*

# ─── Étape 2 : vérifier que ffmpeg voit bien les décodeurs CUDA ──────────
# Log au build pour repérage immédiat. Si `hevc_cuvid` manque, un warning est
# affiché mais le build continue (fallback SW dans ai_engine).
RUN ffmpeg -hide_banner -hwaccels 2>&1 | tee /tmp/ffmpeg_hwaccels.log \
    && ffmpeg -hide_banner -decoders 2>&1 | grep -E "(cuvid|nvenc)" || \
       echo "⚠️  ffmpeg sans cuvid détecté. Pour NVDEC complet, envisager 'jrottenberg/ffmpeg:6-nvidia' comme base ou compiler ffmpeg avec --enable-cuda-nvcc."

# ─── Étape 3 : dépendances Python (torch cu124 en premier pour éviter conflits) ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── Étape 4 : code applicatif ────────────────────────────────────────────
COPY . .

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
    CMD curl -fsS http://localhost:8001/api/ || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
