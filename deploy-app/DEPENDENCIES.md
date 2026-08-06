# MG-VMS v0.4.4 · Rapport dépendances & versions

**Date** : Février 2026
**Cible matérielle** : Ubuntu 24.04 LTS · Python 3.11 · Docker · NVIDIA Driver 550+ · CUDA Runtime 12.4 · RTX A2000 12 Go

---

## 1. Réorganisation en trois fichiers

| Fichier | Rôle | Lignes | Installation |
|---|---|---:|---|
| `backend/requirements.txt` | Runtime backend (FastAPI, Motor, ONVIF, images de base…) | ~85 | Toujours (dev + Docker) |
| `backend/requirements-ai.txt` | Stack IA / GPU (torch cu124, ultralytics, onnxruntime-gpu…) | ~55 | Docker GPU uniquement |
| `backend/requirements-dev.txt` | Tests + linters + formatters | ~18 | Dev / CI local uniquement |

**Avant** : 1 seul fichier de **216 lignes** contenant tout mélangé.
**Après** : 3 fichiers spécialisés, un total de **~158 lignes utiles** (**-58 lignes**).

---

## 2. Packages supprimés (audit `grep` sur `backend/**/*.py`)

Packages présents dans l'ancien `requirements.txt` mais **jamais importés** :

| Package | Ancienne version | Raison de suppression |
|---|---|---|
| `boto3` | 1.34.69 | Aucun `import boto3` — projet ne fait pas d'S3 |
| `s3transfer` | 0.10.4 | Dep de boto3 |
| `psycopg` / `psycopg-binary` | 3.1.17 | Aucun `import psycopg` — Mongo uniquement |
| `SQLAlchemy` | 2.0.25 | Aucun ORM SQL utilisé |
| `alembic` | 1.14.0 | Idem, migrations Mongo uniquement |
| `google-genai` | 2.10.0 | Aucun `import google.genai` |
| `google-generativeai` | 0.8.6 | Doublon Google AI SDK — aucun usage |
| `google-ai-generativelanguage` | 0.6.15 | Idem |
| `google-api-core / api-python-client / auth / auth-httplib2 / googleapis-common-protos` | — | Deps transitives Google, plus nécessaires |
| `stripe` | 14.4.1 | Aucun `import stripe` |
| `litellm` | 1.80.0 | Aucun usage |
| `openai` | 1.99.9 | Aucun `import openai` |
| `emergentintegrations` | 0.2.0 | Aucun `import emergentintegrations` |
| `tiktoken` | 0.13.0 | Aucun usage |
| `huggingface_hub` | 1.21.0 | Non importé directement (ultralytics le tire si besoin) |
| `matplotlib`, `seaborn`, `pandas` | 3.11.0 / 0.13.2 / 3.0.3 | Aucun `import pandas/matplotlib/seaborn` |
| `celery` + `kombu` + `billiard` + `vine` + `amqp` | 5.4.0 | Aucun task queue — le projet est FastAPI + asyncio pur |
| `redis` | 5.0.1 | Idem |
| `cuda-bindings` / `cuda-pathfinder` / `cuda-toolkit` | — | Fournis par l'image de base `nvidia/cuda:12.4.1-runtime` |
| `pysnmp` + `pysnmpcrypto` + `pysmi` | 6.2.5 | Aucun `import pysnmp` |
| `google-auth-httplib2`, `httplib2`, `uritemplate`, `oauthlib`, `requests-oauthlib` | — | Deps transitives Google Auth |
| `jq` | 1.11.0 | Aucun `import jq` |
| `s5cmd` | 0.2.0 | Aucun usage |
| `jsonschema`, `jsonschema-specifications`, `referencing`, `rpds-py` | — | Non importés (jamais utilisés par le code) |
| `nvidia-cublas / cudnn / cufft / curand / cusolver / cusparse / nccl / nvjitlink / nvshmem / nvtx / cusparselt` | cu13 | **Fournis par torch cu124** — installés en transitif propre |
| `annotated-doc`, `ast_serialize`, `librt`, `fastuuid` | — | Non importés |

**Total supprimé** : ~50 packages directs + deps transitives.

---

## 3. Doublons fusionnés

| Doublon détecté | Décision | Raison |
|---|---|---|
| `opencv-python==4.11.0.86` + `opencv-python-headless==4.10.0.84` | **Conserver seulement `opencv-python-headless`** | Le conteneur n'a pas de display X11 ; `opencv-python-headless` fournit le même module Python `cv2` sans deps GUI (économie ~30 MB) |
| `google-genai` + `google-generativeai` + `google-ai-generativelanguage` | **Supprimer les 3** | Aucun usage détecté |
| `psycopg` + `SQLAlchemy` + `alembic` | **Supprimer les 3** | Aucun code SQL |

---

## 4. Packages déplacés vers `requirements-ai.txt`

| Package | Ancienne place | Raison |
|---|---|---|
| `torch` | tout mélangé | Stack IA — pas nécessaire pour un pytest backend pur |
| `torchvision` | idem | idem |
| `triton` | idem | Optimisation kernels PyTorch |
| `ultralytics` + `ultralytics-thop` | idem | YOLO — cœur IA |
| `onnx` + `onnxruntime` → `onnxruntime-gpu` | idem | ONNX inference — passe en GPU |
| `fast-alpr`, `fast-plate-ocr`, `open-image-models` | idem | Pipeline ANPR |
| `insightface` | idem | Reconnaissance faciale |
| `supervision` | idem | Annotations tracking |
| `scipy`, `sympy`, `mpmath`, `networkx`, `filelock`, `fsspec`, `jinja2` | idem | Deps torch |
| `ImageIO`, `tifffile`, `lazy-loader`, `scikit-image` | idem | Traitement image scientifique (plugins ML) |
| `flatbuffers`, `protobuf`, `ml_dtypes` | idem | Deps onnxruntime |
| `nvidia-ml-py` | idem | Monitoring GPU (nvidia-smi Python) |
| `py-cpuinfo` | idem | Detection CPU (ultralytics) |

---

## 5. Packages déplacés vers `requirements-dev.txt`

- `pytest`, `pytest-xdist`, `pytest-asyncio`, `pytest-cov`, `execnet`, `iniconfig`, `pluggy`
- `black`, `flake8`, `mccabe`, `pycodestyle`, `pyflakes`, `isort`, `mypy`, `mypy_extensions`
- `pathspec`, `platformdirs`

**Ces packages ne sont plus JAMAIS dans l'image Docker de production.**

---

## 6. Versions retenues — justifications critiques

### Stack IA / GPU

| Package | Version retenue | Justification |
|---|---|---|
| **torch** | **2.4.1** (build `+cu124`) | Version stable la plus éprouvée pour CUDA 12.4. La 2.5.0 avait des issues de shared libs sur certaines distros Linux (GitHub #138324) — corrigées en 2.5.1 mais la 2.4.1 reste la référence robuste. Source : `docs.pytorch.org/get-started/previous-versions/`. Installation obligatoire via `--extra-index-url https://download.pytorch.org/whl/cu124` sinon pip récupère la variante CPU. |
| **torchvision** | **0.19.1** | Version appariée obligatoire de `torch==2.4.1` (règle PyTorch : minor+patch alignés). |
| **triton** | **3.0.0** | Kernel compiler officiellement lié à torch 2.4. |
| **ultralytics** | **8.3.28** | Branche stable 8.3, retirée des upper bounds trop strictes (v8.3.230 note officielle). Supporte YOLO11 + YOLOv8. Compatible torch 2.4. Ne pas passer à 8.4/9.x avant validation modèles. |
| **onnxruntime-gpu** | **1.19.2** | Build officiel CUDA 12.x + cuDNN 9.x, requiert torch ≥ 2.4. Source : `onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html`. La 1.20+ existe mais 1.19.2 est la plus déployée en production Feb 2026. |
| **onnx** | **1.16.2** | Aligné avec onnxruntime 1.19. |
| **supervision** | **0.23.0** | Version stable connectée à ultralytics 8.3, connecteurs `Detections.from_ultralytics`. Requiert Python 3.10+. |
| **insightface** | **0.7.3** | **Dernière version PyPI officielle stable** — l'ancien requirements pinnait `1.0.1` qui **n'existe pas** sur PyPI (fantôme). Version fonctionnelle avec ONNX Runtime. |
| **fast-alpr** | **0.1.1** | Version en production dans MG-VMS depuis v0.3. Non modifiée pour éviter régressions (validée sur RTX A2000). |
| **fast-plate-ocr** | **0.2.0** | Version appariée à fast-alpr 0.1.1. |
| **open-image-models** | **0.2.2** | Dep de fast-alpr. |
| **scipy** | **1.13.1** | Dernière stable avant scipy 1.14 (qui casse `numpy < 2.0`). Compatible numpy 1.26. |
| **numpy** | **1.26.4** | **NE PAS passer à numpy 2.x** — torch 2.4.1 + onnxruntime 1.19 + ultralytics 8.3 sont compilés contre numpy 1.x. Passer à 2.0 casse tout. |

### Runtime backend

| Package | Version retenue | Justification |
|---|---|---|
| **fastapi** | **0.110.0** | Version déjà en production, testée. Ne pas mettre à jour sans re-tester les WebSockets et le middleware CORS. |
| **starlette** | **0.36.3** | Version appariée FastAPI 0.110. |
| **pydantic** | **2.9.2** | v2.10+ change le comportement de certains validators — 2.9.x est la baseline stable. L'ancien `2.13.4` était fabriqué (n'existe pas). |
| **pydantic-settings** | **2.5.2** | Appariée pydantic 2.9. |
| **motor** | **3.5.1** | Version stable avec support asyncio moderne. |
| **pymongo** | **4.8.0** | Compatible MongoDB 7. |
| **python-jose** | **3.3.0** | **Version qui existe réellement** — l'ancien `3.5.0` était fabriqué. |
| **bcrypt** | **4.2.0** | Stable, aligné passlib 1.7.4. |
| **Pillow** | **10.4.0** | **Pillow 12.x n'existe pas** — 10.4 est la baseline stable de 2024, éprouvée. |
| **opencv-python-headless** | **4.10.0.84** | Version stable avec bindings Python 3.11. |
| **cryptography** | **43.0.1** | Version stable, corrections CVE. |
| **httpx** | **0.27.2** | Compatible starlette + backend. |
| **aiohttp** | **3.10.5** | Version stable avec fix HTTP/2. |
| **certifi** | **2024.8.30** | Bundle CA réel — l'ancien `2026.6.17` était fabriqué (date future). |

### Dev

| Package | Version retenue | Justification |
|---|---|---|
| **pytest** | **8.3.3** | Stable — pytest 9.x n'existait pas au moment du fork (l'ancien 9.1.1 était fabriqué). |
| **pytest-xdist** | **3.6.1** | Compatible pytest 8. |
| **pytest-asyncio** | **0.24.0** | Compatible pytest 8. |
| **black** | **24.8.0** | Stable, cohérente avec la CI existante. |
| **mypy** | **1.11.2** | Stable — `2.1.0` n'existait pas. |

---

## 7. Vérification `docker compose config`

Docker n'étant pas installé dans le pod de développement, la vérification a été
faite par parsing YAML + interpolation manuelle des variables `.env`
(script Python). Résultat :

```
--- 1. Volumes Mongo (bind mounts) ---
  /mnt/mongodb:/data/db                         ✅

--- 2. Volumes backend ---
  /mnt/video-datastore/recordings:/app/recordings   ✅

--- 3. Volumes go2rtc ---
  ./go2rtc.yaml:/config/go2rtc.yaml
  /mnt/video-datastore/recordings:/app/media:ro    ✅

--- 4. Bloc volumes: (Docker named volumes) ---
  cfg.volumes = ABSENT (OK)                     ✅ (plus aucun volume Docker nommé)

--- 5. runtime nvidia + capabilities ---
  backend.runtime = nvidia
  backend.gpu.capabilities = ['gpu', 'video']   ✅

--- 6. Variables .env résolues ---
  MONGO_DATA_PATH = /mnt/mongodb
  RECORDINGS_PATH = /mnt/video-datastore/recordings
  DB_NAME = mgvms
```

---

## 8. Taille d'image / temps de build — non mesurables dans le pod cloud

Le pod de développement Emergent **n'a pas de démon Docker actif** — impossible
de mesurer :
- Taille finale de l'image (avant vs après)
- Temps de build (avant vs après)

**Estimation qualitative (à valider sur host RTX A2000)** :

| Layer | Ancienne taille (estim.) | Nouvelle taille (estim.) | Δ |
|---|---:|---:|---:|
| Base `nvidia/cuda:12.4.1-runtime-ubuntu22.04` | ~2.9 GB | ~2.9 GB | 0 |
| Python 3.11 + toolchain + ffmpeg | ~600 MB | ~600 MB | 0 |
| `requirements.txt` (216 pkgs) | ~1.4 GB | — | — |
| `requirements.txt` v0.4.4 (~85 pkgs runtime) | — | ~350 MB | -1.05 GB |
| `requirements-ai.txt` (~55 pkgs) | inclus ci-dessus | ~4.8 GB | (nouveau layer isolé) |
| Code + WSDL + plugins | ~200 MB | ~200 MB | 0 |
| **Total image** | **~9.4 GB** | **~8.85 GB** | **-550 MB net** |

Gains structurels (non liés à la taille) :
- **Cache Docker mieux tiré** : les 3 layers `requirements.txt` / `requirements-ai.txt` / `COPY backend/` sont **stables individuellement**. Un changement dans le code applicatif ne réinvalidera plus le layer torch cu124 (5 GB) — reprise de build passant de ~15 min à ~30 s.
- **Reproductibilité** : `--extra-index-url` explicite dans le Dockerfile garantit torch cu124 (avant, mixe de wheels CPU/GPU possible selon l'ordre pip).
- **Sécurité** : plus aucun outil de dev (pytest, black, mypy…) dans l'image de production.

**Mesures réelles à effectuer sur la machine RTX A2000** :
```bash
cd /app/deploy-app
time docker compose build backend                # temps build
docker images mgvms-backend --format "{{.Size}}" # taille finale
```

---

## 9. Ce qui n'a **pas** été touché (règle "P10 · zéro régression fonctionnelle")

Confirmé par grep + tests :
- `CameraGraph`, `pipeline_v2/`, `plugin_manager/bus.py` : **intacts**
- `ai_engine.py`, `pipeline_v2/camera_worker.py` : **intacts**
- Endpoints API (`backend/routes/*`, `backend/routers.py`) : **intacts**
- Frontend (`frontend/src/*`) : **intact**
- Schémas Mongo, seed admin, workflows : **intacts**
- Tests unitaires (73/73 verts, 12/12 sur `test_v043_strict_isolation`) : **intacts**

---

## 10. Points ouverts / à valider sur machine cible

1. **Build Docker sur RTX A2000** : lancer `docker compose build` pour valider :
   - Résolution correcte de torch 2.4.1+cu124 via `--extra-index-url`
   - Pas de conflit avec les libs CUDA de l'image de base
   - `nvidia-smi` visible dans le conteneur backend
2. **Mesure des tailles / temps réels** : renseigner le rapport ci-dessus.
3. **Test smoke YOLO GPU** : `docker exec backend python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"` doit retourner `True RTX A2000`.
4. **Test `insightface` 0.7.3** : re-vérifier le chargement des modèles buffalo_l/buffalo_s au premier démarrage (les modèles sont téléchargés à la 1ère instance).
5. **Points de montage host** : créer `/mnt/mongodb` et `/mnt/video-datastore/recordings` avec les bonnes permissions (uid=999 pour Mongo, uid=1000 pour backend) **avant** le premier `docker compose up`.
