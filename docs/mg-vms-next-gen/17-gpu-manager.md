# Chapitre 17 — GPU Manager

> **Version** : v1.0 · **Date** : 2026-07-24 · **Chapitres liés** : `11-plateforme-plugins` · `20-diagnostics-intelligents`

Gestion et allocation des ressources GPU (CUDA, TensorRT, VRAM) entre plugins IA. Un seul GPU peut servir plusieurs plugins avec allocation intelligente.

---

## 17.1 Détection

Au boot, le GPU Manager :
- Détecte les GPUs NVIDIA (nvidia-smi).
- Récupère : modèle, VRAM totale, driver, CUDA version.
- Teste NVDEC, NVENC, TensorRT, CUDA inference.
- Publie l'état dans `db.system.gpu`.

Support multi-GPU (v3.5+).

## 17.2 Allocation VRAM

Chaque plugin déclare dans son manifest son besoin VRAM (`spec.resources.vram_mb`).

Le GPU Manager :
- Suit l'allocation cumulée par GPU.
- Refuse le chargement si dépassement.
- Propose des alternatives (autre GPU, plus petit modèle, CPU fallback).

Politique par défaut :
- Réserve 500 MB VRAM pour le système.
- Alerte à 80% occupation.
- Dégradation gracieuse à 90% (auto-downgrade modèles).

## 17.3 Backends d'inférence

Le GPU Manager peut router les plugins vers différents backends :
- **CUDA** (PyTorch natif) — défaut, universel.
- **TensorRT** (NVIDIA optimizer) — 2-3× plus rapide, mais modèles à convertir.
- **OpenVINO** (Intel) — cible Intel iGPU (v3.2+).
- **CPU** (ONNX Runtime) — fallback universel.

Un plugin peut supporter plusieurs backends (déclaré dans manifest). Le GPU Manager choisit selon disponibilité et policy admin.

## 17.4 Benchmark

Endpoint `POST /api/v1/system/gpu/benchmark` :
- Lance un pipeline de test (encode + decode + inference).
- Mesure FPS, latence, VRAM peak.
- Retourne classement backends.

Utile installateur : "sur cette machine, TensorRT donne +40% vs CUDA".

## 17.5 Diagnostic

- Panne CUDA runtime → tous plugins IA passent CPU auto + notification.
- VRAM saturée → notification proactive + suggestion.
- Température GPU > 85°C → warning (throttling imminent).

## 17.6 Var d'env de bypass

- `MGVMS_AI_FORCE_CPU=1` — force tous plugins IA en CPU (test rapide sans rebuild).
- `MGVMS_GPU_DISABLED=1` — désactive entièrement le GPU Manager.

## 17.7 Tests

- TA-17.1 : Détection GPU au boot → infos publiées.
- TA-17.2 : Allocation VRAM 2 plugins → cumul correct.
- TA-17.3 : Dépassement VRAM → plugin refusé + suggestion.
- TA-17.4 : Bench CUDA vs TensorRT sur modèle YOLO.

## Annexes

| v1.0 | 2026-07-24 | Rédaction initiale |
