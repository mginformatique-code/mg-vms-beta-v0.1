## MG-VMS — Product Requirements Document

**Source de vérité stratégique** → voir `/app/memory/VISION.md` (17 priorités officielles).

Ce fichier PRD reste le résumé opérationnel court. La vision détaillée et la
philosophie du produit sont dans VISION.md — toute discussion architecturale
doit s'y référer.

### Original Problem Statement (Feb 2026)

Transformer MG-VMS d'un logiciel de vidéosurveillance en une **plateforme
professionnelle programmable open source**, capable d'accueillir plugins
IA / métier / automation / intégration via un Plugin Manager style
Home Assistant.

Les 4 piliers : VMS professionnel · Plateforme IA · Moteur d'automatisation ·
Écosystème ouvert.

### Personas

- **Utilisateur final** installe uniquement les plugins nécessaires (résidentiel = 2, industriel = 15)
- **Intégrateur** écrit un plugin, le publie sur Marketplace, plus besoin de fork
- **Équipe MG-VMS** : noyau petit et testable (~5000 lignes Python)
- **Installateur terrain** : setup guidé 10–15 min, health dashboard clair

### État Feb 2026 — sessions successives

**Session 1 (précédente)** : Fix régression IA, go2rtc gateway strict, diagnostics AI/sync, doc 28 chapitres, Plugin Manager fondations (interfaces, contexte, registry), Fernet passwords caméras, `/api/v1/` versioning.

**Sessions 2 à 6 (Feb 2026, en cours)** : Plugin Manager NG opérationnel :
- Bus multi-plugin avec 4 politiques fusion ANPR (cascade/highest/vote/compare)
- Loader dynamique manifest YAML + import isolé importlib
- Config store persistant + hot reload + endpoints `/api/plugins/{name}/config`
- 49 plugins isolés dans `/app/data/plugins/` répartis en 11 catégories
- 5 interfaces plugin : FrameAnalyzer, PlateRecognizer, Tracker, Segmenter, PipelineConsumer, EventConsumer
- Pipeline chaîné `bus.dispatch_pipeline()` wired dans `ai_engine.ai_loop` — chaque frame décodée traverse Detector → Tracker → Business → Notifications
- Frontend `PluginManagerNG.jsx` + `PluginConfigDialog.jsx` + `PipelineTestPanel.jsx` (canvas viz)
- Bouton "Installer les deps" (--no-deps par défaut pour protection env)
- 24 tests pytest OK

**Session 7 (Feb 2026, actuelle)** : P1 Stabilisation — vagues 1 & 2
- ✅ Logo dark/light : assets réels intégrés (`mg-vms-logo-light.png` / `-dark.png`)
- ✅ **PTZ ONVIF réel** : l'endpoint no-op remplacé par `ContinuousMove` + `Stop` via `onvif_zeep`
  - 8 commandes : `pan_left/right`, `tilt_up/down`, `zoom_in/out`, `home`, `stop`
  - Nouveaux endpoints : `GET /api/cameras/{id}/ptz/presets`, `POST /api/cameras/{id}/ptz/preset/{token}`
  - UI 8-directions dans LiveView (croix + colonne zoom)
- ✅ **Recorder Health** : `GET /api/diagnostics/recorder-health` — ffmpeg alive, PID OS, dernier segment, gap détecté, continuité 24h (couverture % + trous listés)
- ✅ Health Dashboard UI mis à jour pour la nouvelle forme recorder
- ✅ Suite pytest : 12/12 (health + pipeline + PTZ/recorder) — voir `tests/test_ptz_and_recorder_health.py`

**Session 14 (Feb 2026)** — Pipeline Engine v2 · Refonte architecture IA :
- 🏗️ **Bascule majeure** : le **Pipeline Engine** devient le chef d'orchestre au lieu du Plugin Manager. Les plugins ne pilotent plus, ils **fournissent** (providers) ou **consomment** (consumers).
- 📦 **Nouveau package** `/app/backend/pipeline_v2/` (6 modules, ~1100 lignes) : interfaces (Protocols DetectionProvider/TrackingProvider/PlateRecognitionProvider/PipelineConsumer + dataclasses Frame/BBox/Detection/Track/PlateResult), fusion (6 stratégies configurables par caméra), stages (5 étapes avec timeout+timing), engine (build_default + stats + describe), scheduler (multi-caméra FPS/priorité/backpressure), adapter (compat rétro v1)
- 🎯 **Format PlateResult standard obligatoire** : plate, confidence, bbox, country, processing_time_ms, provider, raw_text, vehicle_type, vehicle_color, track_id, extras
- 🔄 **Tracking centralisé** + **ROI unique partagée** : 1 crop par véhicule réutilisé par TOUS les providers ANPR
- ⚡ Parallélisme providers via asyncio.gather + to_thread
- ✅ Tests : 17 nouveaux + 52 régression = **69/69 OK**

**Session 13 (Feb 2026)** — v0.4 Sprint de stabilisation (correctifs uniquement) :
- 🐳 **Fix Docker plugins** : `context: ../backend` → `context: ..` (racine repo) + `dockerfile: backend/Dockerfile`. Le Dockerfile ajoute `COPY backend/`, `COPY backend/wsdl/`, `COPY data/plugins/` + assertion build-time (échec build si <40 plugins). Fin des 2 plugins fallback en Docker.
- 🔍 **Plugin Loader** : `_resolve_plugins_dir()` enrichi avec le candidat canonical `<backend>/data/plugins` (chemin Docker v0.4) + log clair `plugins_dir: /app/data/plugins (contient 50 entrées)`.
- 📊 **GPU boot log** : `server.on_startup` logge `GPU · Torch=X TorchVision=Y CUDA=OK/INDISPONIBLE (vN) · Device=<name> · N GB` au démarrage.
- 🔄 **Sync runtime ByteTrack** : `PUT /api/plugins/tracking/config` appelle désormais `load_runtime_config()` immédiatement → les paramètres UI sont réellement appliqués au moteur IA sans redémarrage.
- 📈 **Runtime state** : `GET /api/diagnostics/pipeline-metrics` retourne un nouveau champ `runtime` avec `bytetrack` (état réel du moteur), `ai_config` et `gpu` (Torch/CUDA/device). Fin du bug "ByteTrack=False dans monitoring".
- ⚠️ **Message ONVIF clair** : `onvif_camera()` fait un preflight sur `devicemgmt.wsdl` et lève une `FileNotFoundError` explicite ("PAS un problème d'identifiants — reconstruisez l'image Docker") au lieu du message générique trompeur.
- ✅ Tests : 9 nouveaux `test_v04_stabilization.py` + 43 régression = **52/52 pytest OK**
- ✅ **Bug testing agent** (iteration_36) : verdict **fixed** — 12/12 checks API + 17/17 pytest, 50 plugins chargés sans fallback, WSDL 7/7, ByteTrack sync validé (track_thresh=0.3 appliqué immédiatement), GPU/Torch exposés.

**Session 12 (Feb 2026)** — WSDL ONVIF embarqués :
- 🛠️ **Diagnostic** : le package `onvif-zeep-async` distribué via PyPI ne bundle plus les fichiers WSDL → `ONVIFCamera(...)` échouait avec `FileNotFoundError` sur tous les endpoints (PTZ, découverte, capabilities)
- 📦 **34 WSDL/XSD embarqués** dans `/app/backend/wsdl/` (versionnés dans git, dont les 7 essentiels : devicemgmt, media, media2, ptz, events, imaging, deviceio)
- 🏭 **Factory centralisée** `wsdl_path.onvif_camera()` — remplace tous les appels directs à `ONVIFCamera()`, injecte automatiquement `wsdl_dir=WSDL_DIR`
- 🔧 **10 callsites migrés** : 6 dans `routes/camera_control.py` + 4 dans `streaming.py` (PTZ, IR, relais, capabilities, reboot, device_info)
- ✅ **Validation au démarrage** : `validate_wsdl_dir()` log `7/7 essentiels + 16/16 optionnels présents` — warning explicite si un fichier manque
- 🚢 **Dockerfile** enrichi : `COPY wsdl/ ./wsdl/` explicite + assertion build-time (`RUN test -f /app/wsdl/...`) qui fait échouer le build si un WSDL essentiel manque
- 🌐 **Env override** `MGVMS_WSDL_DIR` pour déploiements exotiques
- 🔍 **Nouveau endpoint** `GET /api/diagnostics/wsdl` pour l'UI/monitoring
- ✅ Tests : 8 unitaires + 35 régression = **43/43 OK**

**Session 11 (Feb 2026)** — v0.3 · Config Caméra Modulaire :
- 🎛️ **Nouveau champ** `Camera.enabled_plugins: list[str]` (whitelist des plugins IA activés pour cette caméra — 0 à N plugins)
- 🔌 **Nouvel endpoint** `GET /api/plugins/catalog` — 50 plugins regroupés en 12 catégories principales (ANPR/LPR, Détection IA, Tracking, Segmentation, Feu/Fumée, Sûreté active, EPI, Comptage, Retail, Parking, Agriculture, Notifications, Événements) avec icônes lucide-react
- 🔀 **Filtrage `dispatch_pipeline`** : si `camera_config.enabled_plugins` non vide, seuls les plugins listés (par `name`) sont dispatchés — sinon fallback legacy (tous les plugins actifs)
- ⚙️ **`ai_engine._do_downstream_work`** passe `enabled_plugins=cam.get("enabled_plugins")` au bus
- 🎨 **Nouveau composant React `CameraPluginsConfig.jsx`** : catalogue interactif avec recherche live, expand/collapse par groupe, sélection multi (tout activer/retirer, cocher tout par groupe), badges d'interface (`PipelineConsumer` / `PlateRecognizer` / `Tracker`…)
- 🔧 **`Cameras.jsx`** : le composant s'affiche quand `detect_enabled=true` (la case reste comme kill-switch global caméra)
- ✅ Tests : 6 unitaires + 13 HTTP e2e + 30 régression = **49/49 OK** (testing_agent iter35, zéro bug)

**Session 10 (Feb 2026)** — v0.3 · Correctif final audit RTSP/ANPR :
- 🧹 **Garde-fou supprimé** dans `frame_source.start()` — plus de refus d'URL non-go2rtc (audit v0.3)
- 🐧 **ffmpeg 5.1.9 installé** dans le container (`apt-get install -y ffmpeg`)
- 🔀 **Workers démos** : `_sync_frame_source_workers` démarre aussi un worker persistant pour les caméras démo (via `rtsp://127.0.0.1:8554/cam_XXX` — go2rtc en local) au lieu de skipper
- ⚙️ **GO2RTC_RTSP=rtsp://127.0.0.1:8554** ajouté à `.env` (résolution hostname `localhost`→`::1` refusée par ffmpeg dans le container Kubernetes)
- 📊 **Métrique alpr_ms** : maintenant enregistrée dans `pipeline_metrics.record_stage()` — visible dans le dashboard
- 🎯 **ANPR par crop véhicule** : `_alpr.predict(vehicle_crop)` remplace `_alpr.predict(img)` — meilleure précision, associations plate↔owner naturelles (audit)
- 🔍 **Nouvel endpoint** `/api/diagnostics/frame-source` — état runtime des workers ffmpeg (alive/last_frame_age/restart_count)
- 📉 **Cache _plate_cache raccourci à 1s** — laisse anpr_tracker gérer les doublons via track_id, permet multi-OCR par véhicule mobile

### Résultats mesurés (avant → après)
| Métrique      | Avant   | Après (p95) | Gain     |
|---------------|---------|-------------|----------|
| fetch_ms      | 2720 ms | **3-4 ms**  | **~700×** |
| yolo_ms       | 128 ms  | 138 ms      | idem     |
| tracking_ms   | 2 ms    | 1 ms        | idem     |
| alpr_ms       | 0 (non affiché) | **36 ms** | affiché ✓ |
| realtime_ms   | 2895 ms | 260 ms avg  | **11×**  |
| downstream_ms | 9 ms    | 13 ms       | idem     |
| Workers actifs | 0       | **1** (demo-cam-002)   | ✓       |

- ✅ Tests : 6 unitaires audit + 23 régression = **29/29 OK**

**Session 9 (Feb 2026)** — v0.3 · Séparation moteur IA / moteur Streaming :
- 🎯 **Découplage go2rtc / IA** : `_sync_frame_source_workers` lit désormais l'URL RTSP native de la caméra (`camera.ai_rtsp_url` prioritaire → `camera.rtsp_url` → fallback go2rtc uniquement pour démos). Env `MGVMS_AI_DIRECT_RTSP=1` (défaut) active le mode direct. go2rtc = streaming/WebRTC uniquement.
- ✅ **Nouveau champ** `Camera.ai_rtsp_url` : URL dédiée IA (flux principal HD) permettant d'utiliser un flux différent que celui exposé aux clients WebRTC.
- ✅ **Module `anpr_tracker.py`** : accumulateur par `track_id` ByteTrack avec machine à états `ENTERED → PRESENT → LEFT` :
  - `record_reading(camera_id, track_id, PlateReading)` — accumule OCR par track
  - `tick_missing(camera_id, seen_tids)` — marque tracks disparus, émet EXIT après `lost_cycles`
  - `best_reading()` — consensus par texte + confiance max
  - Anti-doublons stationnés (1 seul ENTRY) + retente véhicules mobiles (multi-OCR)
- ✅ **Intégration `_analyze_frame`** : chaque plate détectée est routée via anpr_tracker (flag `_emit`) ; downstream ne persiste que les plates avec `_emit=True`.
- ✅ **Nouveaux endpoints diagnostics** :
  - `GET /api/diagnostics/anpr-tracker` — config + véhicules trackés par caméra
  - `GET /api/diagnostics/streaming-metrics` — go2rtc streams (producers/consumers/WebRTC clients) — **séparé** du pipeline IA
- ✅ **Frontend `/pipeline-monitor` enrichi** : panneau Streaming go2rtc (streams live) + panneau ANPR Tracker (véhicules suivis, états, meilleure plaque)
- ✅ **Tests** : 9 unitaires (`test_v03_ai_streaming_decoupling.py`) + 10 HTTP (testing_agent) = **19/19 OK**

**Session 8 (Feb 2026)** — P0 · Pipeline IA temps réel non-bloquant :
- 🔴 Bug fatal réparé : SyntaxError dans `ai_engine.py` (bloc `if _pipeline_ok and _pr:` mal indenté) qui empêchait le backend de démarrer
- ✅ **Refactor `_process_camera`** en Phase A (SYNC ≤200ms) / Phase B (fire-and-forget) :
  - Phase A : fetch_frame → YOLO + ByteTrack + broadcast overlay → return
  - Phase B : `asyncio.create_task(_process_downstream)` — Multi-ANPR, Smart Zones, Workflows, Plugin bus, Event persistence
  - Backpressure guard : `_MAX_DOWNSTREAM_INFLIGHT=2` par caméra, drops enregistrés
- ✅ **`pipeline_metrics.py` enrichi** : `record_stage()` par étape (fetch/yolo/tracking/alpr/realtime/downstream), `record_drop()`, snapshot avec avg/max/p95 par stage, fps_5s, drops_5s
- ✅ **ByteTrack activé par défaut** : `enabled=True, track_thresh=0.25, match_thresh=0.85, track_buffer=60, id_persist_seconds=120` — objectif : minimiser la perte d'IDs
- ✅ **Ordre des routers corrigé** dans `server.py` : `plugin_config_router` désormais AVANT `plugins_bus_router` (sinon `/api/plugins/tracking/config` intercepté par `/plugins/{name}/config`)
- ✅ **Frontend `/pipeline-monitor`** (`AIPipelineMonitor.jsx`) : dashboard temps réel avec bandeau agrégé, cartes caméras expandables (StageBar avec cible), ByteTrack Tuner, objectifs P0, diagramme d'architecture
- ✅ Route + menu ajoutés (`nav.pipeline_monitor` = "Pipeline IA · Live", section Admin)
- ✅ Tests : 11 unitaires `test_pipeline_realtime.py` + 9 HTTP intégration (testing agent) = **20/20 OK**
- Métriques observées démo : downstream_ms=5.6ms (fire-and-forget confirmé), tracking_ms=51ms (ByteTrack actif), drops=0

### Architecture ancrée

- **Backend** : FastAPI + MongoDB + go2rtc strict gateway
- **Frontend** : React + Vite
- **Plugin Manager NG** : `/app/backend/plugin_manager/` (interfaces, bus, loader, fusion, policy, config_store, bootstrap)
- **49 plugins isolés** : `/app/data/plugins/{nom}/manifest.yaml + plugin.py + config/schema.json`

### Roadmap active (voir VISION.md pour le détail)

Ordre officiel confirmé par le CEO :
1. **P1 Stabilisation** — bloquant (PTZ WebRTC, ONVIF, enregistrements, RTSP, FFmpeg supervision, watchdog, reconnexions, health dashboard caméras)
2. **P2 Plugin Manager** — 60% fait, reste sandbox + Fernet secrets + marketplace scaffolding + SDK
3. **P8 ANPR refonte** — cycle Entrée/Présence/Sortie
4. **P3 Smart Zones** — puis P4 Workflow Engine (le combo qui définit MG-VMS)
5. **P13 Health Dashboard**, P5 Timeline, P6 Timeline Photos, P7 Recherche, P9 Audio, P10 Contrôle caméra, P11 Sécurité, P12 HW accel multi-vendor, P14 Marketplace, P15 UX, P16 Stats anonymes, P17 Auto-update

### Ce qui NE doit PAS être fait

- Reconnaissance faciale immédiate (P7 prépare seulement le terrain)
- Concurrence directe avec Frigate/Blue Iris/Milestone
- Nouvelles features avant que P1 stabilisation ne soit garantie
