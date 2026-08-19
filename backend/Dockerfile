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
# v1.0-rc4.3 · Python 3.11 EXPLICITE : l'image ubuntu22.04 fournit Python 3.10
# par défaut, or le freeze qualifié exige 3.11 (ex: contourpy==1.3.3).
# ⚠ Le dépôt universe de jammy ne propose que 3.11.0~rc1 (release candidate
# figée) → PPA deadsnakes pour un Python 3.11.x FINAL maintenu.
# ------------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common gnupg ca-certificates \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3.11-venv \
    python3.11-distutils \
    build-essential \
    ffmpeg \
    tesseract-ocr \
    curl \
    wget \
    git \
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
# pip pour Python 3.11 + liens python3/pip3 → 3.11
# (/usr/local/bin précède /usr/bin dans PATH : le python3.10 système reste
#  intact pour apt, mais TOUT l'applicatif utilise 3.11)
# ------------------------------------------------------------------------------
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
 && ln -sf /usr/bin/python3.11 /usr/local/bin/python3 \
 && ln -sf /usr/bin/python3.11 /usr/local/bin/python \
 && ln -sf /usr/local/bin/pip /usr/local/bin/pip3

# ─── TEST DE BUILD : échec immédiat si Python < 3.11 ───────────────────
RUN python3 --version && python3 --version 2>&1 | grep -Eq "Python 3\.11\." \
    || (echo "ERREUR BUILD : Python 3.11 requis, trouvé: $(python3 --version 2>&1)" && exit 1)
RUN python3 -m pip --version && python3 -m pip --version | grep -q "python 3.11" \
    || (echo "ERREUR BUILD : pip ne cible pas Python 3.11" && exit 1)

# ------------------------------------------------------------------------------
# Python dependencies (couche cache indépendante des sources)
# v1.0-rc4.3 · Le contexte de build est la RACINE du repo (deploy-app compose :
# context: .. / dockerfile: backend/Dockerfile) → chemins relatifs à la racine.
#
# `requirements.txt` = freeze COMPLET et RÉSOLUBLE : les conflits de pins
# hérités (opt-einsum/paddle, google-genai/httpx/anyio, opencv-python) ont été
# corrigés puis re-qualifiés — le résolveur pip standard passe SANS --no-deps.
# litellm est installé depuis l'asset Emergent (URL directe dans le fichier) ;
# l'extra-index-url est requis pour `emergentintegrations`.
#
# v3.1.1 · 2e --extra-index-url pour torch/torchvision==...+cu124 : sans lui,
# pip résout torch depuis l'index par défaut (build CUDA la plus récente,
# incompatible avec le driver hôte figé sur CUDA 12.4) et YOLO tourne
# silencieusement en CPU (torch.cuda.is_available() == False, aucune erreur).
# ------------------------------------------------------------------------------
COPY backend/requirements.txt ./requirements.txt
RUN python3.11 -m pip install --upgrade pip && \
    python3.11 -m pip install --no-cache-dir -r requirements.txt \
        --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ \
        --extra-index-url https://download.pytorch.org/whl/cu124

# ─── Normalisation opencv (déterminisme) ───────────────────────────────
# Les 4 variantes opencv (python/headless/contrib/contrib-headless) écrivent
# dans le MÊME répertoire `cv2` : la dernière installée gagne — l'ordre du
# résolveur est arbitraire. On force la variante contrib (superset : inclut
# cv2.text requis par le plugin opencv-ocr) en toute fin, à version identique.
RUN python3.11 -m pip install --no-cache-dir --force-reinstall --no-deps \
        opencv-contrib-python==4.10.0.84

# ─── TEST DE BUILD : contourpy==1.3.3 réellement installé + imports clés ──
RUN python3.11 -c "import contourpy, sys; assert contourpy.__version__=='1.3.3', contourpy.__version__; print('contourpy', contourpy.__version__, 'OK sur', sys.version)"
RUN python3.11 -c "import cv2; assert hasattr(cv2,'text'), 'module contrib cv2.text absent'; print('cv2', cv2.__version__, '+ contrib OK')"
# v3.1.1 · Échec immédiat si pip a silencieusement pris une build CPU/mauvais
# CUDA au lieu de +cu124 (le pod de build n'a pas de GPU — on ne peut pas
# tester torch.cuda.is_available() ici, seulement la build installée).
RUN python3.11 -c "import torch; assert '+cu124' in torch.__version__, f'build torch inattendue: {torch.__version__} (attendu +cu124)'; print('torch', torch.__version__, 'OK')"
RUN python3.11 -c "import fastapi, motor, cv2, litellm; print('imports critiques OK')"

# ------------------------------------------------------------------------------
# Sources applicatives (embarquées dans l'image · pas de bind mount en prod)
# ------------------------------------------------------------------------------
COPY backend/. .

# Plugins dynamiques : le loader résout `<backend>/data/plugins` = /app/data/plugins
COPY data/plugins/ /app/data/plugins/

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
