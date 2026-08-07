# ==============================================================================
# MG-VMS · Backend · Production Dockerfile v1.0
# ==============================================================================
# Basé sur nvidia/cuda pour tirer parti du GPU (YOLO + FastALPR + OCR).
# Pour un serveur CPU-only, override du service dans docker-compose.override.yml
# (retirer runtime nvidia + deploy.resources.devices).

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

LABEL maintainer="MG Informatique"
LABEL application="MG-VMS Backend"
LABEL version="1.0"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV TZ=Europe/Paris

WORKDIR /app

# ------------------------------------------------------------------------------
# OS packages (ffmpeg pour capture RTSP + OpenCV deps)
# ------------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    ffmpeg \
    curl \
    wget \
    git \
    ca-certificates \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    tzdata \
 && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
 && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------------------
# Python dependencies (couche cache indépendante des sources)
# ------------------------------------------------------------------------------
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ------------------------------------------------------------------------------
# Sources applicatives (embarquées dans l'image · pas de bind mount en prod)
# ------------------------------------------------------------------------------
COPY . .

# ------------------------------------------------------------------------------
# Dossiers persistants (mount points — les données réelles arrivent via volumes)
# ------------------------------------------------------------------------------
RUN mkdir -p \
    /video-datastore \
    /video-datastore/recordings \
    /video-datastore/clips \
    /video-datastore/snapshots \
    /models \
    /crops \
    /logs \
    /certificates \
    /backups

# ------------------------------------------------------------------------------
# Healthcheck (backend expose GET /health)
# ------------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
    CMD curl -fs http://localhost:8001/health || exit 1

EXPOSE 8001

# Uvicorn plutôt que `python3 server.py` (server.py ne définit pas __main__).
# --host 0.0.0.0 requis (container) · --workers 1 car pipeline IA garde l'état
# en mémoire (multi-worker casserait le hot-reload + caches).
CMD ["python3", "-m", "uvicorn", "server:app", \
     "--host", "0.0.0.0", \
     "--port", "8001", \
     "--workers", "1", \
     "--log-level", "info", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
