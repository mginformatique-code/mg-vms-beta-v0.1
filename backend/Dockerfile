# MG-VMS · Backend Docker image (v0.4.4)
# ================================================================================
# Cible :
#   - Host   : Ubuntu 24.04 LTS · NVIDIA Driver 550+ · nvidia-container-toolkit
#   - Image  : nvidia/cuda:12.4.1-runtime-ubuntu22.04 · Python 3.11
#   - Stack  : FastAPI + Motor + Torch 2.4.1 (cu124) + Ultralytics 8.3 +
#              onnxruntime-gpu 1.19 + FFmpeg NVDEC
#
# Ordre d'installation (v0.4.4 · dépendances désormais scindées) :
#   1. requirements.txt     — runtime backend seul (FastAPI, Motor, ONVIF, ...)
#   2. requirements-ai.txt  — stack IA (torch cu124, ultralytics, onnx...)
#   requirements-dev.txt N'EST JAMAIS INSTALLÉ dans l'image de production.
#
# Build context = racine du repo (voir docker-compose.yml). Chemins relatifs
# à la racine : ``backend/requirements*.txt``, ``backend/``, ``data/plugins/``…

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

WORKDIR /app

# ─── Étape 1 · Python 3.11 + toolchain + FFmpeg NVDEC/NVENC ──────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
      software-properties-common ca-certificates curl gnupg lsb-release \
      python3.11 python3.11-venv python3-pip python3.11-dev \
      gcc g++ pkg-config \
      libgl1 libglib2.0-0 \
      ffmpeg \
    && ln -sf /usr/bin/python3.11 /usr/bin/python \
    && ln -sf /usr/bin/python3.11 /usr/bin/python3 \
    && python -m pip install --upgrade "pip>=24.2" "setuptools>=75" "wheel>=0.44" \
    && rm -rf /var/lib/apt/lists/*

# ─── Étape 2 · Vérification décodeurs CUDA FFmpeg (informatif) ───────────
RUN ffmpeg -hide_banner -hwaccels 2>&1 | tee /tmp/ffmpeg_hwaccels.log \
    && ffmpeg -hide_banner -decoders 2>&1 | grep -E "(cuvid|nvenc)" || \
       echo "⚠ ffmpeg sans cuvid — envisager 'jrottenberg/ffmpeg:6-nvidia' pour NVDEC complet."

# ─── Étape 3a · Runtime backend (couche cachable, ~250 MB) ───────────────
# Ce layer contient FastAPI, Motor, ONVIF, etc. Il ne change quasiment jamais.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ─── Étape 3b · Stack IA GPU (couche cachable, ~5 GB) ────────────────────
# Torch cu124 est extrait du repo officiel PyTorch pour garantir le build CUDA.
# Les autres deps IA prennent leur wheel PyPI standard.
COPY backend/requirements-ai.txt ./requirements-ai.txt
RUN pip install --no-cache-dir \
      --extra-index-url https://download.pytorch.org/whl/cu124 \
      -r requirements-ai.txt

# ─── Étape 4 · Code applicatif ────────────────────────────────────────────
# WSDL ONVIF embarqués : indispensables pour découverte ONVIF hors-ligne
COPY backend/wsdl/ ./wsdl/
COPY backend/ .

# v0.4 · Bundle plugins (répertoire copié explicitement, sinon PluginLoader
# ne trouve que les 2 fallbacks built-in au lieu des 50+ plugins).
COPY data/plugins/ ./data/plugins/

# ─── Étape 5 · Assertions de build (fail-fast) ───────────────────────────
RUN test -f /app/wsdl/devicemgmt.wsdl && test -f /app/wsdl/media.wsdl && \
    test -f /app/wsdl/ptz.wsdl && test -f /app/wsdl/events.wsdl && \
    test -f /app/wsdl/imaging.wsdl && test -f /app/wsdl/deviceio.wsdl && \
    test -f /app/wsdl/media2.wsdl && \
    echo "WSDL check OK ($(ls /app/wsdl/*.wsdl | wc -l) WSDL, $(ls /app/wsdl/*.xsd | wc -l) XSD)"
RUN plugin_count=$(ls -d /app/data/plugins/*/ 2>/dev/null | wc -l) && \
    test $plugin_count -ge 40 && \
    echo "Plugins check OK ($plugin_count plugins présents)" || \
    (echo "❌ Seulement $plugin_count plugins trouvés (attendu >= 40). Build échoué." && exit 1)

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
    CMD curl -fsS http://localhost:8001/api/ || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
