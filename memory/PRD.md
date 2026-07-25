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
- **[NEW]** PluginBus + 4 politiques fusion ANPR + PolicyStore + loader dynamique
- **[NEW]** **49 plugins** répartis en **11 catégories**
- **[NEW]** 2 nouvelles interfaces `Tracker` + `Segmenter`
- **[NEW]** **Pipeline chaîné `bus.dispatch_pipeline()`** : Detector → Tracker → Segmenter → PipelineConsumer → EventConsumer (opt-in)
- **[NEW]** Interface `PipelineConsumer` avec méthode `consume(frame, PipelineResult) → list[event]`
- **[NEW]** `PipelineResult` unifié (detections + tracks + masks + business_events + timing par étape + plugins_used)
- **[NEW]** Endpoint `POST /api/plugins/pipeline/test` avec `detections_seed` (test sans caméra)
- **[NEW]** **Vraies implémentations Tracker** : ByteTrack + BoT-SORT via `ultralytics.trackers` (BYTETracker/BOTSORT réels)
- **[NEW]** **Vraie implémentation Segmenter** : Mask R-CNN via `torchvision.models.detection.maskrcnn_resnet50_fpn`
- **[NEW]** **7 plugins métier réels PipelineConsumer** :
  - `person-counting` : traversée de ligne + count in/out + occupancy
  - `vehicle-counting` : par type (car/truck/bus/moto/vélo)
  - `occupancy` : polygone de zone + capacité max + alerte over-capacity
  - `fire-detection` : filtre label fire/flame + cooldown alerte
  - `smoke-detection` : filtre label smoke + cooldown
  - `weapon-detection` : filtre label knife/gun/pistol/rifle → CRITICAL
  - `fall-detection` : heuristique aspect ratio + persistance (≥2s allongé) + hystérésis
- **[NEW]** Bus dispatch pour `Tracker`/`Segmenter`/`PipelineConsumer` en parallèle
- **[NEW]** Notifications Telegram/Discord/SMTP (vraies impl HTTP)
- **[NEW]** Suites pytest — **24/24 OK** (test_pipeline_chain.py ajouté, 3 tests pipeline)

### CHANGELOG (session précédente)
- Fix régression IA (retry, découplage YOLO/ALPR, plus de suicide loop)
- go2rtc gateway strict (frame_source + recorder)
- Endpoints diagnostics `ai-health` + `streams-sync`
- Chiffrement Fernet mots de passe caméras (crypto_utils.py)
- 28 chapitres de doc architecturale `/app/docs/mg-vms-next-gen/`
- Plugin Manager PoC (interfaces + context + registry)
- URL versioning `/api/v1/` (middleware alias)

### ROADMAP prioritaire
- **P0** : ✅ Multi-plugin ANPR/Tracking (fait)
- **P0** : ✅ 11 plugins ANPR + 8 Object Detection Providers + configuration UI (fait)
- **P0** : ✅ 5 Tracking + 3 Segmentation + 3 Notifications + 20+ métier (fait)
- **P0** : ✅ Groupement par catégorie dans l'UI (11 groupes)
- **P1** : Brancher les vrais moteurs sur les plugins skeleton (currently pass-through) — ex: ByteTrack via Ultralytics, SAM2 via Meta
- **P1** : Bridge Object Detection → Tracker → Segmenter (pipeline chaîné dans le bus)
- **P1** : Modulariser `routers.py` → `/app/backend/routes/*.py`
- **P1** : Chiffrement Fernet des secrets plugin dans config_store
- **P2** : Marketplace ecosystem + SDK Python publiable pip
- **P2** : Sandboxing sub-process + container
- **P2** : Namespace DB isolé par plugin (`db.plugin_data.{name}`)
- **P2** : Bus dispatch pour Tracker + Segmenter (actuellement seul FrameAnalyzer/PlateRecognizer/EventConsumer dispatchent)
