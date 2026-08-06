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

**Session 45 (Feb 2026)** — v0.5.2.c · **Map Center Phases 2/3/4** :
- 🎨 Phase 2 : cônes de couverture colorés vert/jaune/rouge (heuristique
  angle+portée+hauteur), badges IA (ANPR/PTZ/TH/IA/REC) sous l'icône
  caméra avec contre-rotation.
- 📋 Phase 3 : Mode Audit (halo jaune sur caméras en défaut + panneau
  synthèse + liste cliquable), photos par caméra (upload dataURI 5 types
  réelle/install/câble/armoire/env, max 4 MB), toggles couches
  (FOV/Noms/IA/Statut).
- 📐 Phase 4 : outils mesure Distance/Surface/Rayon (utilise
  `scale_m_per_px` du plan), exports PNG (canvas Konva x2), PDF
  (fenêtre imprimable avec image + tableau caméras), CSV caméras,
  CSV audit.
- 🗄️ Backend : `MapPositionInput.photos: list` (persistance photos).
- 📊 Tests : 1 nouveau backend (photos) + 102/102 critiques verts.

**Session 44 (Feb 2026)** — v0.5.2.b · Sidebar sous-menus + renommages :
- 📂 Sous-menus dépliables : **Accueil** (Welcome Center + Tableau de bord)
  et **Événements** (Événements + Alertes + Recherche véhicule).
- 🇫🇷 Renommages FR : Pipeline Center → **Suivi des performances**,
  Workflows → **Automatisations**, Événements IA → **Événements**.
- 🧭 Supervision réseau déplacée dans Administration.
- ✅ Sidebar finale à 6 groupes : OPÉRATIONS · ÉVÉNEMENTS · INTELLIGENCE ·
  ADMINISTRATION · JOURNAUX & RAPPORTS · PARAMÈTRES.

**Session 43 (Feb 2026)** — v0.5.2 · **Map Center Phase 1** (Site Designer) :
- 🗺️ Refonte `/map` en Map Center basé sur **Konva.js / react-konva**
  (moteur canvas 2D évolutif : zoom, pan, drag, rotation, layers, mesures).
- 🏗️ Hiérarchie complète : Client → Site → Bâtiment → Niveau → Plan → Caméras.
- 🗄️ Nouveau modèle Mongo : collections `buildings`, `site_plans`, extension
  `cameras.map_position` avec tous les paramètres d'installation (rotation,
  hauteur, angle H/V, portée, objectif, fixation mur/plafond/mât, technicien,
  N° série, date d'installation, notes).
- 🎨 Composants : SiteTree, PlanBackground, CameraNode (FOV wedge coloré +
  statut + halo sélection), CameraPanel droit avec toutes les infos et
  bouton "Voir dans Camera Center" (bidi navigation).
- ⚡ Auto-save position debounced (400 ms), zoom molette centré curseur.
- 🛡️ Sécurité : scope `allowed_sites`, rôle `technician` pour écriture,
  cascade cohérente (delete plan ⇒ désassocie caméras).
- 📊 Tests : 7 nouveaux backend (CRUD, cascade, merge partiel, validation
  image, sites enrichis, auth). Total : 87/87 critiques verts.
- 🚀 Architecture pensée pour Phase 2+ : câbles, switches, NVR, baies,
  Wi-Fi, portes, zones intrusion — pas de refactor requis.

**Session 42 (Feb 2026)** — v0.5.1.d · Réorganisation menu final + Plugin Manager unifié :
- 🧩 Route `/plugins` = **PluginManagerNG** directement (fin du split
  cards + NG). Bouton **Benchmark** ajouté sur chaque plugin d'interface
  `PlateRecognizer` (Gauge → `/anpr-benchmark`).
- 🧭 Sidebar réorganisée en 4 groupes cohérents :
  * Opérations · Intelligence · Administration · **Paramètres** (nouveau).
  * Rapports, Journal d'audit, Journal de diagnostic, Notifications
    déplacés dans le groupe Paramètres.
- 🖥️ Ressources matérielles + Accélération GPU **retirées** de la sidebar :
  accessibles uniquement via 2 nouveaux onglets `Hardware` + `GPU` dans
  le Pipeline Center.
- 🧹 Cleanup : loader dynamique `pluginPages` (Extensions) supprimé.
- 📊 80/80 tests critiques verts, zéro régression.

**Session 41 (Feb 2026)** — v0.5.1.c · Multi-plugin events + UX corrections :
- 🐛 Bug fix `TrackingPanel` (Pipeline Center) : `trackers` retourné comme
  dict est maintenant normalisé en array côté frontend.
- 🧹 Menu latéral : section "Extensions" dynamique **supprimée**. Tous les
  plugins passent par `/plugins`. Sous-lien `/anpr-benchmark` déplacé en
  Administration.
- 📸 Recherche véhicule (`VehicleSearch.jsx`) : modal détail avec scène
  complète (frame plein), crop véhicule (YOLO), crop OCR (plaque),
  badges plugins et table des lectures multi-moteurs.
- 🔀 Multi-plugin events (fix hardcode fast-alpr/yolo) :
  * `_compute_plugins_used(cam)` → liste unifiée CORE + whitelist.
  * `_prerun_multi_anpr()` extrait : dispatch multi-ANPR AVANT écriture
    des events YOLO ⇒ corrélation par `track_id`.
  * Events YOLO embarquent `plate`, `plate_confidence`, `anpr_readings`,
    `plugins_used`, `track_id`.
  * Plaques persistées embarquent `plugins_used`, `anpr_readings`, `track_id`.
  * `EventViewer` : priorité au champ unifié `plugins_used`.
- 🛡️ Fermeture stricte v0.4.3 **conservée** (whitelist vide ⇒ 0 dispatch).
- 📊 Tests : 94/94 critiques verts (10 nouveaux tests multi-plugin +
  ancien test isolation adapté au nouveau path).

**Session 40 (Feb 2026)** — v0.5.1.a · Welcome Center + TESTING=1 bypass :
- 🏠 **Welcome Center** livré comme écran d'accueil officiel (route `/`).
  Dashboard historique déplacé sur `/dashboard`. Un unique call
  `/api/welcome/summary` agrège : score de santé 0-100 (9 composants),
  version + build + changelog des nouveautés depuis dernière visite,
  alertes système auto-déduites (disque, Mongo, GPU, go2rtc, plugins,
  caméras offline), actualités administrateur (publiables via
  collection `welcome_news`), 4 stats express, 5 conseils contextuels,
  8 Centers en accès rapide, documentation, préférences per-user
  (`welcome_prefs` : hide_until_next_version / always_show /
  important_only / last_seen_version).
- 🔓 **TESTING=1 bypass** (fix dette récurrente 5 forks) : rate-limit
  (`SecurityMiddleware`) et brute-force lockout (`_check_lockout`,
  `_register_failure`) court-circuités quand `TESTING=1`. `conftest.py`
  force le flag pour toute campagne pytest.
- 📊 Tests : 8 tests HTTP live Welcome Center + 5 tests unitaires bypass,
  100 % verts. 84 tests critiques v0.4.x (isolation, latence, drivers,
  pipeline, ANPR qualité) toujours verts. Testing agent iteration_40 :
  100 % succès UI + API, 0 bug.
- 🧭 Menu latéral : "Accueil" + "Tableau de bord" séparés dans le groupe
  Opérations. i18n FR/EN mis à jour (`nav.welcome`).

**Session 19 (Feb 2026)** — v0.4.3 · Stabilisation stricte (audit critique) :
- 🔒 **P1 · Fermeture stricte fail-safe** : `enabled_plugins ∈ {[], null, absent}` ⇒ AUCUN plugin dispatché (plus aucun fail-open). Le CameraWorker est l'unique autorité — aucun plugin ne s'auto-déclenche. Preuve : bench `consumer_calls = 0` sur 10 consumers enregistrés avec whitelist vide/null/absente.
- 🔀 **P2 · Suppression du double encode/decode** : `_fetch_frame` retourne un `ndarray` directement, `_stage_decode` accepte `ndarray` OU `bytes`. Zéro `cv2.imencode` dans la boucle temps réel côté RTSP direct.
- 🗑️ **P3 · Code mort supprimé** : `pipeline_v2/{engine.py, stages.py, interfaces.py, adapter.py, scheduler.py, fusion.py, providers/}` + 2 fichiers de tests morts = **1 406 lignes supprimées**. Une seule architecture pipeline en vie : `CameraWorker + Downstream + PluginBus`.
- 🎯 **P4 · Fusion ANPR unique** : `pipeline_v2.fusion.FusionEngine` supprimé (mort). `anpr_tracker.record_reading` = source unique de vérité pour le vote/consensus.
- 🧹 **P5 · FrameContext nettoyé** : champ `plate_rois` inutilisé supprimé.
- 🔗 **P6 · Frames unifiés** : `FrameContext.as_plugin_frame()` — vue *lazy* sur `plugin_manager.Frame` partageant le buffer numpy et le cache JPEG (memoization par quality). Aucune copie inutile.
- 📤 **P7 · Upload manuel unifié** : `analyze_image_local` réécrit en wrapper thin `CameraWorker("__upload__").analyze(bytes, ["fast-alpr"])`. Une seule implémentation IA.
- 📊 **P8 · Benchmarks réels** : `/app/benchmarks/results_v043.md` — mesures CPU/timings sur 1/5/10/20/30/50 plugins. GPU/VRAM non mesurés (pod cloud sans GPU, différé RTX A2000). Gains clefs : encodes ROI 80→4 pour 20 moteurs ANPR, dispatch scale à 50 plugins.
- 🛡️ **P9 · Tests d'isolation** : `tests/test_v043_strict_isolation.py` — 11 tests couvrant fail-safe (list vide/null/absente), isolation caméra/caméra, absence de fuite téléobjectif→grand-angle.
- ✅ **P10 · Zéro régression fonctionnelle** : Mongo/HDD/CUDA/Docker/CameraGraph/YOLO unique/tracking unique/ROI cache **intouchés**. 57 tests critiques v0.4.3 verts (incl. multi-plugin, sandbox, whitelist strict, isolation).

**Session 18 (Jun 2026)** — v0.4.3 · Refonte « Architecture First » (12 points) :
- 🏗️ **Runtime pipeline-driven EN PRODUCTION** : `PipelineRuntime → CameraWorker → FrameContext → Stages → PluginBus`. `ai_engine.py` réduit de 1557 à ~500 lignes (acquisition RTSP + modèles + wrappers compat uniquement).
- 🎯 **YOLO 1× / frame** (stage detection du worker) · **Tracking UNIQUE** (`TrackerPool`, 1 tracker/caméra ; plugins tracker convertis en choix d'algo du stage ; `dispatch_pipeline(precomputed_tracks)` court-circuite les plugins Tracker — preuve par SpyTracker jamais appelé).
- 🖼️ **VehicleROI partagé** (1 crop/véhicule, JPEG memoizé) + `Frame.jpeg()` partagé dans les 5 plugins ANPR cloud + thumbnails YOLO lazy + `dispatch_plate(only=whitelist)`.
- 🔬 **Pipeline Inspector** : `GET /api/diagnostics/pipeline-inspector` (13 stages × caméra : avg/max ms, calls, errors, timeouts, FPS + CPU/RAM/GPU/VRAM) + page React `/pipeline-inspector`.
- 📊 **Benchmarks** (`scripts/benchmark_pipeline.py` → `/app/benchmarks/`) : tracking 2× (0.72→0.37 ms), crops 20 moteurs 20× (14.65→0.75 ms, 80→4 encodes JPEG).
- ✅ Préservé : whitelist ANPR per-camera, auto-suspension qualité, caméras spécialisées, infra SSD/HDD/CUDA.
- ✅ Tests : **73/73 OK** (testing agent iteration_39, 0 bug critique). Préexistants hors périmètre : iter30 (1), iter32 (4).

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

**Session 17 (Feb 2026)** — v0.4.2 · Pipeline IA per-camera + Stats plugins fidèles (P0) + ANPR Qualité intelligente + Caméras spécialisées (P1/P2) :

**P0 · Fondation architecturale** :
- 🎯 **CameraGraphRegistry** (`pipeline_v2/registry.py`) — compile un **graphe d'exécution unique par caméra** basé sur `enabled_plugins` : precalcule `needs_detection/tracking/segmentation/business/anpr` + la liste précise des plugins dispatchables par étape. Cache invalidé au hash + rebuild auto sur register/unregister/set_enabled du bus.
- 📊 **Per-camera plugin stats** (`plugin_manager/bus.py`) — `_call_one()` accepte `camera_id` et incrémente `_per_camera_stats[camera_id][plugin_name] = {calls, errors, timeouts, last_ms, last_error}`. Corrige le bug historique "0 calls même quand des plaques sont détectées".
- ⚡ **Skip early dans `_do_downstream_work`** : si le graphe indique `needs_tracking + needs_segmentation + needs_business = tous False` → import bus, reconstruction Detection(), dispatch : tout court-circuité. Zéro allocation.
- 🔒 **Whitelist per-camera étendue au multi-ANPR** : `dispatch_plate` respecte `cam.enabled_plugins` (double filtrage entries + résultats).
- 🔌 **3 endpoints P0** : `/api/diagnostics/pipeline-v2` (graphes), `/pipeline-v2/stats` (per_camera × per_plugin), `/pipeline-v2/invalidate` (force rebuild).

**P1 · ANPR Auto-suspension qualité (Issue #4)** :
- 🧠 **AnprQualityController** (`pipeline_v2/anpr_quality.py`) — évalue chaque frame véhicule sur 3 axes (luminosité, netteté via Laplacian, contraste) + détection heure de nuit. Score composite 0.0-1.0.
- 🚦 **Machine à états ACTIVE ↔ SUSPENDED** avec hystérésis N/M cycles (défaut : 5 bad → suspend, 3 good → resume). Empêche les blips.
- 🔔 **Message UI clair** : `"ANPR suspendu automatiquement — sharpness=42 < 100 (flou)"`.
- ⚙️ **3 endpoints** : `/api/diagnostics/anpr-quality` (états), `/config` (PUT reconfigure à chaud), `/reset` (force reprise).

**P2 · Caméras ANPR spécialisées (Issue #5)** :
- 🎯 **SPECIALIZED_ANPR_MODELS** : détection par `camera.model` de Dahua ITC (413/237/215/352), Hikvision DeepInView (iDS-2CD7A / iDS-2TD81), Axis P1465-LE, Bosch AutoDome IP starlight. Ces caméras **bypass complètement l'auto-suspension** → OCR 24/7.
- 🌙 État renvoyé : `is_specialized: true, specialized_model: "Dahua ITC413 · ANPR 24/7 dédié"`.

**Résultats et vérifications** :
- ✅ Tests : 14 P0 (`test_v041_pipeline_per_camera.py`) + 14 P1/P2 (`test_v042_anpr_quality.py`) + 48 régression = **76/76 OK**
- 📈 **Preuve runtime P0** : sur `demo-cam-002` (whitelist=`[yolo-detection, bytetrack, fast-alpr]`), seul `bytetrack` apparaît dans les stats per-camera. Les 8 PipelineConsumers globalement actifs (person-counting, vehicle-counting, smoke-detection, weapon-detection...) ne sont **jamais** appelés pour cette caméra.
- 📈 **Preuve runtime P1** : sur `demo-cam-002` (mire testsrc2 = score qualité 0.30-0.33), `consecutive_bad` progresse cycle par cycle. Après 5 cycles → OCR auto-suspendu, message UI clair.

**Session 16 (Feb 2026)** — v0.4.1 · Fix bug critique ANPR whitelist :
- 🔴 **Bug critique fixé** : le pipeline ANPR (`_alpr.predict` dans `ai_engine._analyze_frame`) tournait **hors du Plugin Manager** et ignorait `enabled_plugins`. Résultat : FastALPR désactivé sur une caméra → des plaques étaient malgré tout écrites en Mongo.
- ✅ **Fix appliqué** : signature `_analyze_frame(camera_id, frame_bytes, enabled_plugins=None)` + guard `_anpr_skipped = bool(enabled_plugins) and "fast-alpr" not in enabled_plugins` → le bloc OCR est court-circuité (aucun `_alpr.predict`, aucune écriture Mongo, aucun événement). `_process_camera` passe `cam.get("enabled_plugins")`. Comportement legacy (whitelist vide) préservé.
- 🩹 **Correctif intermédiaire iteration_37** : premier fix causait `UnboundLocalError` (`timings["alpr_ms"]=0.0` avant que le dict soit créé). Corrigé en itération 38 avec variable locale `t_alpr = 0.0` initialisée avant le bloc.
- ✅ **bug_testing_agent iteration_38** : verdict **fixed** — sur 35s + 60s de fenêtre "disabled" : 0 nouvelle plaque écrite en Mongo (700 → 700), logs confirment `alpr_ms=0ms` frame par frame, réactivation fast-alpr → 75 ms sur une frame véhicule. Regression endpoints frame-source/bus/catalog OK.
- ⏳ **Minor cosmétique connu** : `pipeline_metrics.alpr_ms.avg` (rolling window 100 cycles) descend progressivement, pas immédiatement à 0 après désactivation (13.2ms après 35s, 3.8ms après 60s). Preuve d'exécution effective venir via `/api/ai/debug` frame-par-frame (=0ms).
- ✅ Tests : 5 nouveaux `test_v041_anpr_whitelist.py` + 71 régression = **76/76 OK**

**Backlog v0.4.1** (points 1, 4-12 non livrés dans cette itération, à traiter séparément) : pipeline par caméra (graphe distinct), stats plugins fidèles (calls/errors/timeout), optimisation zero-copy dispatch, qualité ANPR "no plate > false plate", recommandation automatique ANPR (jour/nuit), désactivation intelligente selon luminosité, détection caméras spécialisées (Dahua ITC / Hikvision DeepInView), assistant configuration, différenciation Installé/Chargé/Actif, préservation bind mounts MongoDB SSD + recordings HDD, runtime CUDA 12.4 + FFmpeg CUDA.

**Session 15 (Feb 2026)** — Pipeline v2 · Provider natif YOLO + Designer + Overlay caméra :
- 🎯 **YoloDetectionProvider natif** (`pipeline_v2/providers/yolo_provider.py`) — implémente `DetectionProvider` v2, réutilise `ai_engine._model` (aucune duplication modèle), gère fallback si YOLO pas chargé
- 🧩 **Pipeline Designer UI** (`/pipeline-designer`) — assemble Camera → Detector → Tracker → ANPR → Fusion → Consumer, catalogue de plugins filtré par interface, sélection multi-providers, 6 stratégies fusion configurables, config JSON compilée en preview. Remplacera à terme le Plugin Manager.
- 🎛️ **CameraControlOverlay** (`/pages/CameraControlOverlay.jsx`) intégré à LiveView — 5 boutons overlay (Projecteur / IR / Sirène / TTS / Reboot) apparaissent au hover sur chaque tuile caméra, actions via `POST /cameras/{id}/relay/{token}/{on|off}`, `POST /cameras/{id}/audio/tts`, `POST /cameras/{id}/reboot`
- 🧭 **Menu** enrichi avec "Pipeline Designer" (section technicien)
- ✅ Tests : 6 nouveaux `test_yolo_provider_and_ui.py` + 69 régression = **75/75 OK**
- 📸 Screenshots validés : Pipeline Designer affiche 12 detectors dans le picker (YOLOv11, YOLOv8, ONNX, TensorRT, OpenVINO, RT-DETR, YOLO-NAS...), LiveView montre les 5 boutons overlay en bas-gauche de chaque tuile

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
