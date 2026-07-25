## MG-VMS Preview NG (v2.30) — État actuel

### Original Problem Statement
Refonte de MG-VMS vers une **plateforme plugin-oriented** (style Home Assistant) où le noyau est minimal et toutes les fonctionnalités (YOLO, ANPR, notifications, parking...) deviennent des plugins isolés avec cycle de vie indépendant. Le core ne connaît jamais l'implémentation d'un plugin, uniquement son **interface** (`FrameAnalyzer`, `PlateRecognizer`, `EventConsumer`).

### Personas
- **Utilisateur final** : installe uniquement les plugins nécessaires (résidentiel = 2, industriel = 15).
- **Intégrateur** : écrit un plugin, le publie sur Marketplace, plus besoin de fork.
- **Équipe MG-VMS** : noyau petit et testable (~5000 lignes Python).

### Architecture ancrée
- **Backend** : FastAPI + MongoDB + go2rtc strict gateway
- **Frontend** : React + Vite
- **Plugin Manager NG** (`/app/backend/plugin_manager/`) :
  - `interfaces.py` — contrats Plugin/FrameAnalyzer/PlateRecognizer/EventConsumer
  - `bus.py` — PluginBus fan-out (isolation crash + timeout + métriques)
  - `fusion.py` — 4 politiques ANPR (cascade/highest/compare/vote)
  - `policy.py` — store de politique persistant (JSON)
  - `builtin/` — wrappers YOLO/ALPR + MockPlate pour tests
  - `bootstrap.py` — enregistrement des plugins bundle au startup
  - `registry.py` — catalogue déclaratif des plugins

### Endpoints clés
- `GET /api/plugins` — catalogue déclaratif (6 plugins bundle)
- `GET /api/v1/plugins/bus` — instances runtime sur le bus (avec métriques)
- `POST /api/v1/plugins/bus/{name}/{enable|disable}`
- `GET /api/v1/plugins/policy` — snapshot politique multi-plugin
- `PUT /api/v1/plugins/policy/anpr` — change mode/threshold ANPR
- `PUT /api/v1/plugins/policy/frame-analyzer`
- `POST /api/v1/plugins/test/multi-anpr` — endpoint QA avec injection de mocks
- `GET /api/v1/diagnostics/ai-health`
- `GET /api/v1/diagnostics/streams-sync`

### CHANGELOG (Feb 2026 — session courante)
- **[NEW]** PluginBus multi-plugin (dispatch parallèle, isolation crash, timeout, métriques)
- **[NEW]** 4 politiques de fusion ANPR (cascade/highest/compare/vote — ADR-16)
- **[NEW]** PolicyStore persistant `/app/backend/data/plugin_policy.json`
- **[NEW]** Wrappers builtin YOLO/ALPR conformes aux interfaces plugin
- **[NEW]** MockPlatePlugin pour tests unitaires multi-ANPR
- **[NEW]** Endpoints `/api/v1/plugins/bus/*` + `/policy/*` + `/test/multi-anpr`
- **[NEW]** Bootstrap plugin bundle au startup (yolo-detection + fast-alpr)
- **[NEW]** Loader dynamique `plugin_manager/loader.py` (manifests YAML + import isolé)
- **[NEW]** Frontend `PluginManagerNG.jsx` avec catégorisation par groupe
- **[NEW]** `/api/plugins/registry` renommé pour éviter conflit legacy
- **[NEW]** **19 plugins isolés** dans `/app/data/plugins/`:
  - 11 ANPR (fast-alpr, plate-recognizer, openalpr, codeproject-ai, paddle-ocr, easyocr, tesseract, google-vision, azure-vision, opencv-ocr, custom-plugin-template)
  - 8 Object Detection (yolo-detection=YOLOv11, yolov8, yolo-nas, rt-detr, efficientdet, openvino-detector, onnx-detector, tensorrt-detector)
- **[NEW]** Métadonnées `providerGroup` dans manifest + regroupement UI par catégorie
- **[NEW]** Système d'états plugin (`ready`/`not_configured`/`missing_dependency`/`error`/`disabled`)
- **[NEW]** Config store persistant + endpoints `GET/PUT /api/plugins/{name}/config` avec masquage secrets + hot reload via `on_config_change`
- **[NEW]** Frontend `PluginConfigDialog.jsx` — formulaire dynamique depuis JSON Schema
- **[NEW]** **Bouton "Installer les deps"** dans l'UI pour plugins `missing_dependency`
  - Endpoints `POST /api/plugins/{name}/install-deps` + `GET /api/plugins/{name}/install-status`
  - Job background `pip install --no-cache-dir --no-deps <packages>` avec timeout 15min
  - Flag `--no-deps` par défaut pour éviter d'écraser numpy/opencv (protection env)
  - Poll toutes les 3s côté frontend + toast + reload auto de l'état plugin
- **[NEW]** Suites pytest : `test_multi_plugin.py` 11 + `test_plugin_loader.py` 4 + `test_anpr_plugins.py` 6 = **21/21 OK**

### CHANGELOG (session précédente)
- Fix régression IA (retry, découplage YOLO/ALPR, plus de suicide loop)
- go2rtc gateway strict (frame_source + recorder)
- Endpoints diagnostics `ai-health` + `streams-sync`
- Chiffrement Fernet mots de passe caméras (crypto_utils.py)
- 28 chapitres de doc architecturale `/app/docs/mg-vms-next-gen/`
- Plugin Manager PoC (interfaces + context + registry)
- URL versioning `/api/v1/` (middleware alias)

### ROADMAP prioritaire
- **P0** : ✅ Multi-plugin ANPR/Tracking (fait — session Feb 2026)
- **P0** : ✅ 11 plugins ANPR + 8 providers Object Detection isolés (fait)
- **P0** : ✅ Bouton "Installer les deps" + configuration UI (fait)
- **P0** : ✅ Groupement par catégorie dans l'UI (fait)
- **P1** : Ajouter **catégorie Tracking** (ByteTrack, BoTSORT, DeepSORT, StrongSORT, OCSORT)
- **P1** : Ajouter **catégorie OCR généraliste** distincte de ANPR (TrOCR, plus détaillé)
- **P1** : Ajouter **catégorie Segmentation** (SAM2, Detectron2, Mask R-CNN)
- **P1** : Catégories spécialisées : Comptage / Parking / Sécurité (Smoke, Fire, Weapon, Fight, Fall) / PPE / Commerce / Agriculture
- **P1** : Notifications Discord/Telegram/SMTP en plugins `EventConsumer` isolés
- **P1** : Modulariser `routers.py` → `/app/backend/routes/*.py`
- **P2** : Chiffrement Fernet des secrets plugin dans le config store
- **P2** : Marketplace ecosystem + SDK Python publiable pip
- **P2** : Sandboxing sub-process + container
- **P2** : Namespace DB isolé par plugin (`db.plugin_data.{name}`)
