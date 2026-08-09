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
**Session 53 (Feb 2026)** — v0.5.7 · **Final Build** · Validator + Matrix + Driver Health (feature complete, freeze) :
- 🔍 Nouveau service `pipeline_v2/driver_validator.py` — validation **non destructive** d'un driver caméra.
  Enum `TestState` : PASS / WARNING / FAIL / TIMEOUT / UNSUPPORTED / SKIPPED. Score pondéré
  (snapshot=25, stream=25, device_info=15, events=15, ptz=10, audio=5, reboot=3, siren=2).
  Les capacités destructives (PTZ, siren, light, audio, reboot) sont validées par **inspection
  de contrat** (méthode surchargée par rapport à `CameraDriver` base), jamais exécutées.
- 📊 Nouveau service `pipeline_v2/capability_matrix.py` — agrégat en lecture seule.
  `build_capability_matrix(group)` avec `group` ∈ {vendor, driver, model, camera}.
  `build_driver_health()` combine `MANIFEST` de chaque driver + stats runtime (cameras_count,
  validations_count, last_validation_at, avg_score).
- 🩺 `MANIFEST` ajouté sur chaque driver (`ONVIFDriver`, `ReolinkDriver`, `HikvisionDriver`,
  `DahuaDriver`) : {driver, version, status: stable|beta|experimental, api, protocols,
  supported_models, coverage_pct}.
- 🌐 Nouveaux endpoints (déclarés AVANT `/{camera_id}/...` pour éviter le shadowing) :
  - `GET /api/devices/matrix?group=vendor|driver|model|camera`
  - `GET /api/devices/drivers/health`
  - `GET /api/devices/{camera_id}/validate?persist=false` (idempotent)
  - `POST /api/devices/{camera_id}/validate` (persiste dans `cameras[id].last_validation`)
- ✅ Tests : nouvelle suite `test_v057_validator_matrix_health.py` (**26 tests**, 100 % mocks).
  Cumul MG-VMS v0.5.7 : **69/69** verts (26 validator/matrix/health + 21 Phase 1 + 22 v0.4.6).
- 🛡️ **Zéro régression** : `/api/devices/_supported` inchangé, structures existantes préservées.
  Aucun frontend modifié. `CameraManager` reste passif. Aucun code destructif ajouté.
- 🧊 **FIN DE BUILD** : v0.5.7 est feature complete. Aucun ajout d'ici la v0.6.


**Session 52 (Feb 2026)** — v0.5.7 · Universal Camera API · Phase 1 (consolidation d'interfaces) :
- 📐 Document de migration `/app/MIGRATION_v057_UNIVERSAL_CAMERA_API.md` avec tableau
  composant/action/décision — approche Option C (fusion progressive, zéro duplication).
- 🎯 Une seule source de vérité : `backend/drivers/` reste inchangé (contrat + implémentations).
- 🔗 `backend/pipeline_v2/camera_driver.py` réécrit en **contrat pur** : re-export du
  `CameraDriver` (ABC), `CameraCapabilities`, `DeviceInfo`, `StreamInfo`, `DeviceStatus`,
  exceptions et registry depuis `drivers/` + ajout d'une facette `CameraDriverProtocol`
  (`runtime_checkable`) pour typing structural. Zéro logique métier.
- 🛠️ `backend/pipeline_v2/camera_manager.py` créé — façade légère qui délègue au
  `CameraDeviceService` (get_driver/discover/release + `validate_camera_doc` sans I/O
  + `supported_vendors`). Aucune commande métier exposée.
- ➕ `CameraCapabilities` enrichi (backward-compatible) avec ~25 nouveaux flags v0.5.7 :
  `multi_stream`, `codec_h265`, `talkback`, `flash`, `ptz_presets/patrol/tracking`,
  `ai_motion/person/vehicle/animal/face/helmet/anpr/line_crossing/intrusion`, `thermal`,
  `radar`, `relay`, `digital_io`, `wifi`, `poe`, `sdcard`, `hdd`, `nas`, `ftp`, `smtp`,
  `cloud`, `https`, `vpn`, `proprietary_api`. Tous à `False` par défaut.
- ✅ Tests : `tests/test_v057_universal_api.py` (21 tests) + suite `test_camera_drivers.py`
  (22 tests) — 43/43 verts. `/api/devices/_supported` répond avec les 5 vendors
  historiques (onvif, reolink, dahua, hikvision, generic) sans changement d'API.
- 🚫 Aucune modification des routes `/api/devices/*`. Aucun changement frontend.



**Session 49 (Feb 2026)** — v0.5.5 · Assistant de découverte réseau avancée :
- 🌐 Nouveau module `/app/backend/routes/discovery.py` : listing des
  interfaces (IP, netmask, CIDR, gateway, vitesse, état, virtual),
  démarrage/annulation/résultat de scan, flux SSE temps réel.
- 🖥️ Refonte complète du dialog « Scan ONVIF » côté frontend
  (`OnvifDiscovery` dans `Cameras.jsx`) : sélection multi-interfaces,
  CIDR personnalisés, console noire style IBM FlashSystem, barre de
  progression + compteurs live, résumé final, export TXT/LOG, annulation.
- 🕵️ Découverte hybride : WS-Discovery multicast + scan CIDR ciblé
  (ports 80/554/8000/8080/8899/2020/8081) + probe SOAP GetDeviceInformation.
- 🏷️ Reconnaissance fabricant (Hikvision, Reolink, Dahua, Axis, Uniview,
  Hanwha, Synology, QNAP, MikroTik, Ubiquiti) via banner HTTP + ONVIF.
- 🖨️ Section « Équipement détecté mais non compatible » (NVR/NAS/imprimantes).
- 🔗 Logo + « MG Informatique » sidebar → lien externe vers mg-vms.com.
- 📊 7/7 tests v0.5.5 verts. Zéro régression sur l'endpoint historique
  `/api/cameras/discover` (préservé intact).

**Session 48 (Feb 2026)** — v0.5.4-B · Security Center + Security Score :
- 🛡️ Nouvelle page `/security-center` avec ring score 0-100 + grade A-E.
- 📋 10 critères pondérés (HTTPS, JWT env, mots de passe, MFA, backups,
  sandbox plugins, firmware caméras, mongo auth, disque, certs TLS).
- 💡 Conseil actionnable par critère non conforme + poids visible (+10).
- 🔗 Bloc "Actions rapides" (Sessions/Utilisateurs/Audit/Caméras).
- 🌐 Sidebar Administration : entrée Centre de sécurité, i18n FR/EN.
- 📊 8/8 tests v0.5.4 verts (score + auth requise).

**Session 47 (Feb 2026)** — v0.5.4-A · Session Manager + timeout :
- 🔐 Sessions tracquées serveur (collection `sessions` Mongo) avec JWT
  enrichi d'un `jti` unique, révocation immédiate, timeout configurable.
- ⚙️ 5 endpoints `/api/security/*` (list, revoke, revoke-others, get/put
  timeout).
- 🖼️ Settings → Sessions actives : sélecteur timeout admin (7 valeurs
  préréglées) + liste sessions (navigateur/IP/dernière activité) + boutons
  déconnecter individuel / toutes-autres.
- ⏰ Popup global `SessionExpiryWatcher` : alerte 60s avant expiration avec
  Continuer/Déconnexion (refresh JWT).
- 🌐 +20 clés i18n FR/EN.
- 📊 108/108 tests critiques verts (6 nouveaux Phase A).
- 📋 Reste à faire : Phases B (Security Center + Score), C (MFA/TOTP),
  D (RBAC granulaire + Camera Score), E (Sandbox+Backups+Notifs),
  F (API Keys + Assistant déploiement + RGPD).

**Session 46 (Feb 2026)** — v0.5.3 · Welcome refactoré + Dashboard allégé :
- 📝 Welcome Center recentré éditorial : suppression Stats+Alertes système,
  ajout **Tutoriels vidéo YouTube** (CRUD admin, miniature auto) et
  **Widgets** style pfSense (notes libres / liens rapides).
- 📊 Dashboard allégé : suppression carte Santé du système (redondante
  avec topbar+Welcome), graphique Activité en pleine largeur.
- 🗄️ 2 nouvelles collections Mongo (`welcome_tutorials`, `welcome_widgets`)
  + 6 endpoints admin.
- 🌐 21 nouvelles clés i18n FR+EN.
- 📊 Tests : aucune régression, 102/102 critiques verts.

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

## Audit v0.7.c — P0 démarrage (2026-06)
- P0-1 Healthcheck: Dockerfile probait /api/ → pointé sur /health + start-period=90s
- P0-2 IA lazy: _load_models conditionné à ≥1 caméra detect_enabled (+ gardes lazy _analyze_frame/analyze_image_local)
- P0-3 TensorRT: libnvinfer.so.10 manquant = warning ATTENDU, fallback CUDAExecutionProvider OK (documenté, zéro code)
- P0-4 Demo cam 002: /app/media du conteneur go2rtc = RECORDINGS_PATH → fichier démo absent → fix montage ../media:/demo-media:ro + chemin go2rtc.yaml
- P0-5 frame-source: _MAX_CONSECUTIVE_FAILURES=10, arrêt propre + gave_up dans status(); fix churn démo dans _ensure_frame_source_running (GO2RTC_RTSP)
- Fichiers: backend/Dockerfile, backend/ai_engine.py, backend/frame_source.py, deploy-app/docker-compose.yml, deploy-app/go2rtc.yaml, go2rtc/go2rtc.yaml (preview: flux démo de base ajoutés)
- Validé: /health 1.6ms local, login/me/docs 200, WS OK, demo-cam online, worker 12FPS restart_count=1, gave_up testé (10 échecs → stop propre)

## Validation exhaustive v0.7.b→v0.7.c (2026-06, audit read-only)
- API: 10/10 endpoints OK (system-health n'existe pas → health-dashboard). Login/me/WS/docs/openapi OK.
- IA lazy: validé (0 cam → aucun chargement; réactivation → load au 1er traitement depuis cache).
- go2rtc: 6 streams, frame.jpeg/RTSP/ports 1984-8554-8555 OK. Snapshot = POST /api/cameras/{id}/snapshot.
- Pipeline: Voiture/Personne/Vélo détectés, bytetrack, fusion hiérarchique en prod (downstream:506), _emit anti-doublons (:518). p95/p99 via /api/diagnostics/pipeline-metrics.
- ANPR: crop mutualisé (VehicleROI = vue numpy, JPEG memoizé), fanout dispatch_plate = asyncio.gather. Gate qualité auto-suspend OCR sur vidéo démo floue (sharpness 21<100) = comportement conçu.
- Mémoire: RSS 1186→1200Mo sur 22min (stable, pas de fuite). CPU-only preview (pas de GPU/VRAM).
- ANOMALIES DOCUMENTÉES (non corrigées, sur consigne):
  A1: deploy-app/docker-compose.prod.yml:55 YAML INVALIDE — `${MGVMS_DOMAIN:?...(ex: vms.exemple.com)}` le `: ` non quoté casse le parse → docker compose config échoue avec l'overlay prod. Fix: quoter la ligne.
  A2: fast-alpr état bus "error·modèle non chargé" figé au bootstrap (pas de refresh après _load_models). Cosmétique, dispatchable=false sans impact (core via plate_registry).
  A3: devices API map unsupported_capability→400 (pas 501 demandé) — routes/devices.py:80-95. Jamais de 500 ✓.
- Backlog v1.0: Performance Gate (seuil 200ms configurable → event Operations Center avec stage responsable).

## v0.7.c Camera API Hardening (2026-06)
- P0-1: _probe_status_once étape 0 = frames fraîches frame_source (<10s) → online prioritaire (source de vérité unique; toutes les UIs lisent cam.status)
- P0-2: OnvifDriver → factory wsdl_path.onvif_camera (wsdl_dir déterministe). Bundle WSDL complété OFFICIEL: onvif.xsd rev 2025 (+StringList), common.xsd, soap-envelope (SOAP1.2), media2 import corrigé. 7 WSDL 100% offline.
- P0-5: mapping devices: unsupported_capability→501, no_driver_available→501, device_error/driver_error→502, fallback 502 (jamais 500)
- P0-4: vérifié UI 100% capability-driven (caps.* partout, zéro logique marque)
- Tests: WSDL parse 7/7, ONVIF init sans FileNotFoundError, P0-1 unit online/offline, battery endpoints sans 500, régression IA/plugins/UI OK
- Limite: appels ONVIF réels (GetServices etc.) non testables sans caméra physique — définitions validées offline

## v0.7.d (2026-06)
- Fix "unknown version"/changelog vide une fois installé : CHANGELOG.md absent de l'image Docker (COPY backend/ . seulement) → ajout `COPY CHANGELOG.md ./CHANGELOG.md` dans backend/Dockerfile. welcome.py lit /app/CHANGELOG.md (OK image + preview).
- Entrée changelog v0.7.c+1 renommée v0.7.d. /api/welcome/summary → installed=v0.7.d, changelog 30 entrées.

## v0.7.e Wave A · Hot Reload chirurgical (2026-06)
- Cause racine : `ai_loop` rechargeait config Mongo + `_sync_frame_source_workers` à chaque cycle (~6×/sec). Fix : signal-driven + TTL 10s. 4,3× moins de queries Mongo mesurées sur 25s.
- Signaux publics dans `ai_engine` : signal_config_changed / signal_camera_config_changed / signal_camera_topology_changed / get_hot_reload_metrics
- Routes camera POST/PUT/DELETE + pipeline-config + anpr-camera-put + bytetrack-config posent le signal approprié
- `_sync_frame_source_workers(cams, only={ids})` — sync ciblé, 1 modif caméra = 1 seul worker. Preuve mesurée : create camera → topology_syncs_partial +1, 0 impact autres workers
- Nouveau `GET /api/diagnostics/hot-reload` (view_live) : compteurs runtime
- Tests : 16 verts (test_v07e_hot_reload_wave_a.py) + 68 régression existants
- Fichiers : ai_engine.py, routers.py, plugin_config.py, plugin_manager/bus.py, routes/health_dashboard.py

## v0.7.e Wave C · Multi-OCR / Crop optimal (2026-06)
- Nouveau module `pipeline_v2/plate_quality.py` : assess_crop_quality (sharpness Laplacien + contraste std + skew Hough), enhance_plate_crop (deskew + CLAHE + unsharp), crop_hash (aHash 16×16), engine_weight (fast-alpr=1.0, tesseract=0.55...), save_debug_bundle
- CameraWorker._stage_anpr : gate qualité + enhance auto + cache (track_id, crop_hash) + debug bundle facultatif
- anpr_tracker.best_reading v2 : fusion pondérée score = Σ (conf × engine_weight). Fast-alpr bat tesseract à confidence égale, mais accumulation tesseract peut battre fast-alpr isolé (robustesse)
- Nouveau `GET/PUT /api/diagnostics/plate-quality[/debug]` : seuils + poids + toggle debug à chaud
- Mode debug (env MGVMS_DEBUG_OCR=1 ou API) sauvegarde bundle /tmp/mgvms_debug_ocr/<cam>_<track>_<ts>/ : frame_full.jpg, vehicle.jpg, plate_raw.jpg, plate_enhanced.jpg, bundle.json
- Cleanup dict result plates : `_plate_crop_np`, `_plate_quality`, `_crop_hash` ne fuient pas en Mongo
- Tests : 19 verts (test_v07e_multi_ocr_wave_c.py). Total : 94/94 verts (16 A + 19 C + 59 régression)
- Fichiers : pipeline_v2/plate_quality.py (nouveau), pipeline_v2/camera_worker.py, anpr_tracker.py, pipeline_v2/downstream.py, routes/health_dashboard.py

## v0.7.e Wave B · Frontend fuites (2026-06)
- Audit statique : 33 intervalles / 2 sources temps-réel (WS + EventSource) / 186 useEffect / 10 addEventListener — TOUS avec cleanup validé
- Fuite B1 identifiée : `aiDetections` map jamais purgée → croissance mémoire linéaire quand caméras ajoutées/supprimées. Fix : TTL 45s + prune 30s dans AppContext + skip re-render si rien à purger
- Fuite B2 : nouvelle map identity à chaque WS message → re-renders inutiles de tous les consommateurs. Fix : skip write si payload identique (même ts + même count boxes)
- Nouveau module `frontend/src/lib/perf.js` : `window.__mgvms_perf.snapshot()` accessible depuis DevTools/Playwright. Compte ws_messages, ws_reconnects, ai_detections_map_size, ai_detections_evictions, intervals/timers actifs, uptime
- Preuves live (Playwright 42s) : ws_messages=28 · map_size=1 stable · evictions=0 · reconnects=0 · UI Welcome affiche v0.7.e correctement
- Fichiers : frontend/src/lib/perf.js (nouveau, 87 lignes), frontend/src/context/AppContext.jsx (+51/-7)

## v0.7.e Wave D · Camera API hardening (2026-06)
- ONVIF `get_capabilities()` enrichi : probes audio_input/output/two_way, events (Profile T → onboard_ai), snapshot URI + HTTPS detection, multi_stream (>=2 profils), codec_h265, ptz_presets
- Bundle WSDL local offline validé (test dédié) : devicemgmt/media/ptz/imaging/events/analytics/accesscontrol + xsd
- Contrat "preview stable pendant modif caméra" renforcé (short-circuit `all_match` dans register_camera_stream + signal-driven Wave A)
- Tests : 8 verts (TestWsdlBundle 2 + TestOnvifCapabilitiesProbing 5 + TestIdempotentCameraUpdate 1)
- Fichier : backend/drivers/onvif_driver.py (+60/-6)

## v0.7.e Wave E · Timeline Reolink + miniatures + boucle vidéo (2026-06)
- Palette timeline LiveView `EVENT_KIND_META` alignée sur la demande utilisateur : 🟦 person=#0044FF · 🟩 car=#00E676 · 🟨 motorbike=#FFB800 · 🟧 truck=#FF6600 · 🟪 bus=#9333EA · 🟥 animal=#FF3333 · 🟫 bicycle=#8B4513. Alertes critiques rouge/orange préservées
- Galerie véhicule Vehicles.jsx expose désormais les 3 crops distincts : photo complète (lien overlay), crop véhicule (miniature 100×96), crop plaque (bandeau bas 100×32 cliquable). Le crop plaque = version optimisée Wave C (deskew/CLAHE/sharpen)
- data-testid ajoutés : `gallery-frame-link-<id>`, `gallery-vehicle-thumb-<id>`, `gallery-plate-link-<id>`, `gallery-plate-thumb-<id>`
- Fix boucle vidéo Recordings.jsx : `<video onEnded>` handler qui passe automatiquement au segment suivant (comportement Reolink-like). Sans ce handler la vidéo restait bloquée sur la dernière frame — perçu à tort comme "boucle sur le même segment"
- Tests : 10 verts (TestVehicleGalleryHasThreeCrops 2 + TestTimelinePaletteMatchesRequest 7 + TestRecordingsAutoNextSegment 1)
- Fichiers : LiveView.jsx (+11/-14), Vehicles.jsx (+38/-18), Recordings.jsx (+12)

## Total pytest v0.7.e (Waves A+B+C+D+E)
- 112/112 verts (16 Wave A + 19 Wave C + 18 Wave D+E + 59 régression ciblée)
- Zéro API publique modifiée, zéro régression

## v0.7.e Wave F · Stress-test 1→50 caméras (2026-06)
- Harness reproductible `backend/stress/stress_test.py` — mesure asyncio.gather 1/5/10/20/30/50 cams × 3 frames
- Environnement preview CPU-only 8 vCPUs 32 GB — pas de GPU NVIDIA détecté (nvidia-smi absent)
- YOLOv8n (6.25 MB) auto-téléchargé + warmup, CPU inference
- Résultats mean total pipeline (ms) : n=1→106.5 · n=10→523.8 · n=50→2782.6 (goulot YOLO CPU-only qui scale linéaire N)
- **Wave C stages négligeables** : assess_crop_quality ~0.8ms constant, crop_hash ~0.1ms, enhance short-circuit → total Wave C < 1 ms peu importe N
- RAM stable à 1088 MB RSS après 50 cams (pas de fuite ; delta -12 MB entre n=30 et n=50 = convergence GC)
- CPU cap ~145% (~1.45 core) — YOLO CPU tient GIL par gros blocks
- Extrapolation GPU RTX 3060 : cible <200ms tenue jusqu'à N=50 (YOLO 30-50ms + Wave C 1ms + OCR 80-120ms ≈ 150ms)
- Rapports : /app/memory/WAVE_F_STRESS_TEST_v0.7.e.md + STRESS_TEST_v0.7.e_report.json (données brutes)

## Rapport consolidé Waves A→F : /app/memory/RAPPORT_FINAL_v0.7.e.md
- 112 tests verts (16 A + 19 C + 18 D+E + 59 régression) — zéro régression, zéro API publique modifiée
- ~1300 lignes livrées + 53 nouveaux tests
- 4 endpoints diagnostic runtime : /api/diagnostics/hot-reload, /api/diagnostics/plate-quality[/debug], window.__mgvms_perf.snapshot()
- 8 rapports MD dédiés dans /app/memory/

## v0.7.f Wave G · YAML Prod Fix + HTTPS/TLS UI (2026-06)
- YAML fix `deploy-app/docker-compose.prod.yml` lignes 53-55 : quoting explicite des `${VAR:?message}` (le `:` dans `(ex: vms.exemple.com)` cassait le parsing). Test `TestDockerComposeProdYaml` verrouille + guard anti-régression pour tout `${VAR:?message: hint}` non-quoté
- Nouveau router backend `/api/security/tls/*` (8 endpoints, permission admin) : GET/PUT domains, GET/upload/self-signed/activate/delete certificates, GET pem export audité
- Clé privée chiffrée AES-GCM 256 avant persistance Mongo (nonce 96b + AAD `mgvms-tls-key`, dérivée de JWT_SECRET SHA-256) — jamais stockée en clair
- Match cert/key vérifié à l'upload (public_numbers comparaison). Hostname RFC 1123 strict (regex). Suppression du cert actif refusée 409
- Nouvelle page frontend `TlsSettings.jsx` (route `/security-center/tls`) : 4 tuiles résumé + panneau Domaines/Routing + panneau Certs stockés (badges statut/expiration) + panneau Génération auto-signée (CN + SAN DNS/IP wildcards + validité + taille RSA) + panneau Import PEM (drag&drop file) + aide contextuelle. 80 data-testid dont 30+ tls-*
- Action rapide "HTTPS / TLS · Domaines & certificats" ajoutée dans SecurityCenter
- Tests : 8 verts (test_v07f_tls_settings.py). Total v0.7 : 120/120 verts
- Fichiers : deploy-app/docker-compose.prod.yml (+5/-3), backend/routes/tls.py (nouveau, 340l), backend/server.py (+2), frontend/src/pages/TlsSettings.jsx (nouveau, 477l), frontend/src/pages/SecurityCenter.jsx (+6/-1), frontend/src/App.js (+2)

## v0.7.g Wave H · Pipeline Inspector Live + Robustesse globale (2026-06)
- Axe 1 UI : nouvelle page `/diagnostics/pipeline-inspector` (PipelineInspectorLive.jsx, 260 lignes) — auto-refresh 2s, consomme 3 endpoints diagnostic en parallèle, affiche System (CPU/RAM/RSS/GPU) + Hot Reload (Wave A) + Gate qualité (Wave C) + tableau détaillé par caméra (avg 60s · p50 · p95 · p99 · max · calls · err · budget bar colorée)
- Axe 1 backend : `pipeline_v2/inspector.py::_StageStat.to_dict()` ajoute p50_60s/p95_60s/p99_60s/samples_60s sur fenêtre 60s
- Axe 10 : ErrorBoundary React racine (fallback sobre + retry/reload) + handlers window (unhandledrejection + error) → compteurs `window.__mgvms_react_errors` / `_unhandled_rejections` / `_window_errors`
- Axe 4/10 audit backend : 0 pattern dangereux (locks sans timeout / sleep dans coroutine / blocking sync dans routes async / requests bloquant) — aucune correction nécessaire
- Preuve Playwright : 13 stages actifs mesurés en live sur `demo-cam-002` (fetch/decode/motion/yolo/tracking/roi/anpr/dispatch/multi_anpr/scenarios/persist) avec bars colorées et percentiles
- Tests : 6 verts (test_v07g_pipeline_inspector.py) — total v0.7 : **126/126**
- Fichiers : pipeline_v2/inspector.py (+18), pages/PipelineInspectorLive.jsx (nouveau, 260l), components/ErrorBoundary.jsx (nouveau, 55l), index.js (+20), App.js (+2)

## Rapport Wave H : /app/memory/WAVE_H_INSPECTOR_ROBUSTESSE_v0.7.g.md
Répond aux 10 axes de l'audit demandé et aux 9 critères de validation, avec preuves.

## v0.7.h Wave I · QoS & Production Hardening (2026-06)
- OCR Quality Score 0-100 : `CropQuality.score_100` propriété + `to_dict()` — score composite lisible UI/events
- OCR Engine Reliability : nouveau module `pipeline_v2/engine_reliability.py` (110l) — apprentissage online rolling accuracy 100 lectures × (camera, engine), mult 0.5-1.5 neutre <10 lectures. Endpoint `GET /api/diagnostics/engine-reliability`. Intégration fusion deferred v0.7.i
- Surveillance permanente + alertes QoS : `pipeline_v2/qos_alerts.py` (170l) — boucle 15s scan inspector + system, émet `qos_alert` dans `events` (visible Ops Center). Seuils configurables (pipeline_total_ms=200, yolo=50, anpr=120, fps_min=5, ram=85%, gpu_vram=90%). Anti-flap 30s. `GET/PUT /api/diagnostics/qos-thresholds`
- Preuve live : 6 alertes émises en 20s sur demo-cam-002 preview CPU-only (`yolo_slow p95=232ms`, `pipeline_slow avg=250.7ms`, `fps_low 0.43<5`)
- Audit MongoDB : `stress/mongo_audit.py` (140l) — détecte missing_index / missing_ttl / large_no_time_index. Rapport JSON `/app/memory/MONGO_AUDIT_v0.7.h.json`. 17 recommandations preview (5 events, 5 plates/recordings, 3 TTL, 2 tls_certificates)
- Tests : 10 verts (test_v07h_qos_hardening.py). Total v0.7 : **136/136 verts**
- Fichiers : plate_quality.py (+8), engine_reliability.py (nouveau, 110l), qos_alerts.py (nouveau, 170l), server.py (+3), routes/health_dashboard.py (+40), stress/mongo_audit.py (nouveau, 140l)

## v0.8-rc1 · Camera Health Score + Capabilities Matrix (2026-06)
- `backend/services/camera_health.py` (nouveau, 170l) : score 0-100 par caméra basé sur 7 signaux pondérés (FPS 25%, pipeline_reliability 20%, ocr_quality 15%, rtsp 15%, latency_p95 10%, onvif_freshness 10%, event_freshness 5%). Bands healthy≥80 / degraded≥55 / critical<55. Retourne signals détaillés + top 5 reasons
- 3 endpoints : GET /api/cameras/{id}/health, GET /api/cameras/health (avec summary), GET /api/cameras/capabilities-matrix (vendor×caps + vendor_summary)
- Preuve live : demo-cam-002 score 61.1 (degraded) — 47% conf OCR + pas d'ONVIF heartbeat = reasons visibles immédiatement
- Tests : 4 verts (test_v08rc_camera_health.py). Total : **140/140 verts**
- Fichiers : services/camera_health.py (nouveau, 170l), routes/health_dashboard.py (+60), tests (+55)

## Rapport v0.8-rc1 : /app/memory/v0.8-rc1_CAMERA_HEALTH.md

## Backlog v0.8 RC complet (12-14 sessions dédiées pour v0.8 GA)
Prioritisé par ROI décroissant (détails dans le rapport v0.8-rc1) :
- P4 Pipeline Auto Optimizer (YOLO batch/résolution/fréquence + désactivation OCR faibles)
- P3 OCR Learning multi-dim (par pays/luminosité + intégration reliability_mult dans fusion)
- P2 Crop ANPR Premium (multi-marges + upscale + retry auto si score<60)
- P1 Concrete drivers vendor : Hikvision ISAPI, Dahua CGI, Reolink, Axis VAPIX, Uniview, Hanwha, Bosch (3-5 sessions)
- P5 Virtualisation React (react-window Vehicles/Events/Cameras/Timeline pour 100k+ items)
- P7 Playback pro (timeline click → lecture immédiate + garantie synchro)
- P8 Ops Center Monitoring UI (dashboard temps réel avec pastilles vert/orange/rouge)
- P9 Tests résilience (chaos monkey Mongo/go2rtc/camera reboot/GPU OOM)
- P10 Rapport validation finale (taux ANPR/faux positifs-négatifs/stabilité longue durée)
- Feature 2 : Installation Quality Report (Map Center exploite hauteur/angle + ANPR success rate → recommandations)

## Reste à backporter du v0.7.i
- Intégrer reliability_mult dans anpr_tracker.best_reading
- Recrop auto multi-marges si Quality Score<60
- Frontend ErrorBoundary par section (isole chaque tab)
- Stress-test panne (déjà couvert par P9 v0.8 RC)
- Job cron 24h simulation avec logs perf p95/p99 par heure
- ~~Création auto indexes Mongo au bootstrap~~ ✅ **v0.8-rc3**

## v0.8-rc3 · MongoDB Auto-Indexes + React Virtualization (2026-08)
### Backend — MongoDB Auto-Indexes bootstrap
- `backend/database.py` refonte : nouveau helper `_safe_index()` tolérant aux `OperationFailure`
  (code 85 IndexOptionsConflict + 86 IndexKeySpecsConflict) et aux erreurs génériques. Bootstrap
  ne crashe jamais si un index existe déjà avec des options différentes (ex : TTL préexistant).
- Application des 17 recommandations issues de `stress/mongo_audit.py` :
  * cameras : id, site_id, status
  * events : timestamp, camera_id, type, kind + composé (camera_id, timestamp desc)
  * plates : plate, timestamp, camera_id, track_id + composé (plate, timestamp desc)
  * recordings : camera_id, start_ts, end_ts + composé (camera_id, start_ts desc)
  * audit_logs : timestamp, actor
  * sessions : user_id, created_at
  * tls_certificates : id, active (v0.7.f)
  * alerts : timestamp, camera_id
- Preuve runtime : `list_indexes()` confirme 32 indexes créés sur 8 collections critiques
  (avant : ~10). Backend startup log propre, zéro erreur.

### Frontend — VirtualGrid react-window v2
- Nouveau composant `frontend/src/components/VirtualGrid.jsx` (~110 lignes) — grille
  responsive virtualisée basée sur `react-window@2.3.0`. Rend uniquement les cellules
  visibles ± 2 overscan. Colonnes calculées dynamiquement via `ResizeObserver`
  (min-column-width + max-columns).
- Hybride intelligent : sous le `threshold` (défaut 200 items), fallback rendu classique
  CSS grid (pas de régression UX pour les datasets modestes). Au-delà, activation Grid
  virtualisée automatique.
- Intégration `Vehicles.jsx` : la grille manuelle `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3
  xl:grid-cols-4` remplacée par `<VirtualGrid ...>`. Preuve écran : 31 véhicules rendus
  identiquement (sous threshold), zéro erreur React, testid présents.
- Data-testid : `virtual-grid`, `virtual-grid-virtualized` (+ data-count/columns/rows).

### Tests
- Nouveau `tests/test_v08rc3_mongo_indexes_virtualization.py` — 7 tests verts (helpers,
  indexes présents, VirtualGrid contract, Vehicles.jsx wired). Total : **147 tests verts**.

### Fichiers modifiés
- `backend/database.py` (+80 lignes, refactoring)
- `frontend/src/components/VirtualGrid.jsx` (nouveau, 110 lignes)
- `frontend/src/pages/Vehicles.jsx` (+8 / -5, intégration)
- `frontend/package.json` (+1 dep : react-window@2.3.0)
- `backend/tests/test_v08rc3_mongo_indexes_virtualization.py` (nouveau, 130 lignes)

## v0.8-rc4 · FEATURE FREEZE · Stabilisation Sprint 1 (2026-08)
- 🧊 **Mandat** : plus aucune nouvelle feature/écran/refonte. Focus exclusif
  stabilité + qualité ANPR + performances + zéro régression.
- **Audit read-only** : 5 causes racines mesurées (disque plein 93 %, QoS
  spam 10/5min, blobs Mongo 6.6 KB/plate, frames drop 95 %, hot-reload
  partial jamais déclenché).
- **Fix #1 disque** : craco memory cache → 93 % → 86 % + prévention permanente
- **Fix #2 QoS spam** : backoff progressif 30s → 60s → 120s → 300s (réduction
  volumétrie ~90 % attendue)
- **Deferred Sprint 2** : #3 blobs Mongo (major refactor), #4 frames drops
  (investigation queue), #5 hot-reload topology partial signal
- Tests : 8 nouveaux verts (test_v08rc4_stabilisation_sprint1.py). Total : 56/56
- Preuves runtime : 0 React error / 0 unhandled rejection / 0 window error
  (Playwright post-fix)
- Fichiers : `frontend/craco.config.js` (+8), `backend/pipeline_v2/qos_alerts.py`
  (+35 / -8), tests (+160)

## v0.8-rc5 · FEATURE FREEZE · Stabilisation Sprint 2 (2026-08)
- 🎯 **Priorité #2 absolue** : Crop Premium v2 · cascade multi-variants
  déclenchée UNIQUEMENT si score_100 < 60. 6 marges (0→+25 %) × 3 méthodes
  (enhance + denoise + perspective_correct). Additif — fast-path préservé.
- 📊 **Priorité #3** : Frames Dropped catégorisation. Compteurs distincts
  `backpressure` / `rtsp_timeout` / `decode` exposés dans
  `/api/diagnostics/frame-source` → l'opérateur voit d'un coup d'œil
  si un "95 % dropped" est normal (backpressure) ou anomalie.
- **Preuves mesurées** :
  * Fast-path (score ≥ 60) : 0.61 ms avg → coût négligeable
  * Escalade (score = 39) : +31 points de qualité → 70/100 en 376 ms
    (12 variants testés sur CPU cloud sans GPU)
- Tests : 13 nouveaux verts (test_v08rc5_crop_premium_frames_categorized.py).
  Total suite : 87/88 (1 flaky pré-existant hors périmètre).
- Fichiers : `backend/pipeline_v2/crop_premium.py` (nouveau, 245 lignes),
  `camera_worker.py` (+25 / -3), `downstream.py` (+1),
  `frame_source.py` (+18 / -1), tests (+175)

## v0.8-rc6 · FEATURE FREEZE · Stabilisation Sprint 3 (2026-08)
- 🔬 **Priorité #7** : Pipeline Trace End-to-End · suit UNE détection
  Frame→Decode→Motion→YOLO→Tracking→ROI→ANPR avec timings exacts par
  stage. Sampling léger (1/100 frames, ajustable). Ring buffer 50 traces.
- 🩺 **Priorité #4** : Camera State Fusion · un état caméra fusionne 4
  signaux (frame_source, pipeline_activity, go2rtc, tcp). Une caméra
  produisant des frames RTSP est TOUJOURS online — fin des faux Offline.
- **Preuves mesurées live** :
  * Trace live pipeline demo-cam-002 : total = 109.65 ms
    (yolo = 102.06 ms = 94 % → goulot identifié · GPU → total < 200 ms)
  * Camera state demo-cam-002 : online avec 100 % confidence (4/4 signaux)
- 6 endpoints diagnostic ajoutés (traces × 4 + camera-state × 2)
- Tests : 18 nouveaux verts (test_v08rc6_state_fusion_and_tracing.py).
  Suite complète : 103/103 verts, zéro régression.
- Fichiers : `pipeline_v2/trace.py` (155 l), `pipeline_v2/camera_state.py`
  (200 l), `camera_worker.py` (+20 / -5), `routes/health_dashboard.py`
  (+95), tests (+215)

## v0.8-rc7 · FEATURE FREEZE · Stabilisation Sprint 4 · Phase Qualification (2026-08)
- 📊 **Priorité #4** : Stability Watcher permanent — snapshot minute-par-
  minute (72 h × 60 min ring buffer). Capture Backend + Pipeline + Mongo +
  go2rtc. Agrégats p50/p95/p99 sur fenêtres 1h/6h/24h/72h + uptime_pct
  des dépendances.
- 🌪 **Priorité #3** : Chaos Test Harness Enterprise — 5 scénarios
  non-destructifs (rtsp_worker_state, inspector_flood, trace_overflow,
  qos_alert_flood, mongo_failure). Batch runner + rapport JSON.
- **Preuves mesurées live** :
  * Watcher 1er snapshot : CPU 17.5 % · RAM 37 % · RSS 822 MB · Mongo 0.9ms
  * Chaos 5/5 verts en 0.29 s (qos_alert_flood : 99 bloqués sur 100)
- 3 endpoints diagnostic stability + CLI `python -m stress.chaos`
- Tests : 14 nouveaux verts. Suite complète : 117/117 verts.
- Fichiers : `pipeline_v2/stability_watcher.py` (230 l),
  `stress/chaos.py` (200 l), `server.py` (+3), `health_dashboard.py`
  (+45), tests (+190)

## v1.0-rc4 · P0 Fusion Événements/Véhicules + Réparation Plugins OCR (2026-08)
### P0-1 — Fusion UI (FAIT, testé iter_41 100%)
- UNE seule vue `/events` : chips Tous/Plaques/Véhicules/Personnes/Camions/Bus/Deux roues/Animaux.
- Chip « Plaques » = intégralité de l'ancien module Véhicules (`VehiclesSection embedded` — recherche IA groupée, identités, anomalies, drawer 6 onglets). Zéro perte de fonctionnalité.
- `/vehicles` redirige vers `/events?filtre=plaques` ; entrée « Véhicules » retirée de la sidebar.
- EventViewer enrichi : bouton « Historique du véhicule » (ouvre VehicleDrawer), « Voir dans la Timeline », Analyser OCR (existant).
- Recherche IA sur TOUTE la vue Événements (`/api/smart-search` retourne désormais `events[]` complets ; time-only ⇒ date du jour ; camera_hint ; plaque ; couleurs).
- `GET /api/events` accepte `types=` (multi-types CSV).

### P0-2 — Plugins OCR (FAIT, testé)
- CAUSE RACINE : installeur pip `--no-deps` ⇒ paquet installé mais deps transitives absentes ⇒ import KO ⇒ « DEP MANQUANTE » persistait malgré un toast succès.
- FIX `loader.install_dependencies` : install AVEC deps + fichier de contraintes (numpy/torch/opencv/ultralytics figés) + install apt des deps système + VÉRIFICATION post-install (`verified_state`) — plus jamais de faux succès.
- Environnement preview : easyocr READY, tesseract READY (binaire apt installé), opencv-ocr READY (opencv-contrib), fast-alpr READY.
- paddle-ocr : paddlepaddle/paddleocr/paddlex installés MAIS segfault C++ du moteur d'inférence sur **aarch64** (preview ARM). Plugin blindé par sonde sous-processus (`_probe_isolated`) → état `error` honnête, backend JAMAIS crashé. Sur le build Docker x86_64 client : fonctionnel (deps dans requirements.txt + tesseract-ocr dans Dockerfile backend).
- Benchmark multi-moteurs : `POST /api/system/anpr-benchmark?engines=...&fusion=true` → par moteur : avg/min/max ms, cpu_pct, ram_delta_mb, plaques lues, meilleure lecture + fusion vote majoritaire. UI `/anpr-benchmark` : cases YOLO/FastALPR/PaddleOCR/EasyOCR/OpenCV OCR/Tesseract/Tous + case Fusion Multi OCR + tableau résultats.

### P0-3 — UI = état réel backend (FAIT, testé)
- CAUSE RACINE fast-alpr : état évalué UNE fois au bootstrap AVANT le chargement paresseux du modèle ALPR ⇒ « ERREUR modèle non chargé » figé.
- FIX : `bus.refresh_lazy_states()` (opt-in `refresh_state_lazy()` par plugin) appelé par GET /plugins/bus, le benchmark, et warm-up différé 20s/60s au bootstrap.

### Restant / Backlog
- P0 HTTPS ERR_SSL_PROTOCOL_ERROR (vérif TLS nginx docker) — NON TRAITÉ cette session.
- Mocks HTTP caméras RTSP physiques (tests skippés).
- P1 : VirtualGrid sur Events/Timeline ; Pipeline Auto Optimizer ; migration routers.py → routes/.
- Rapport de tests : /app/test_reports/iteration_41.json (backend 7/7, frontend 100%).

## v1.0-rc4 · Smart Search fix EMERGENT_LLM_KEY prod + fallback (2026-08)
- **Cause racine** : la clé LLM était présente automatiquement dans le pod preview Emergent mais **absente du container backend en production** (ni dans `.env.example`, ni transmise via `docker-compose.yml`).
- **Fix chirurgical 6 fichiers** :
  * `backend/routes/smart_search.py` : code normalisé `SMART_SEARCH_LLM_NOT_CONFIGURED` (503) au lieu de 500 générique. Message explicite pointant vers `.env`.
  * `backend/routes/vehicles.py` : même politique sur le second endpoint.
  * `deploy-app/.env.example` : `EMERGENT_LLM_KEY=` avec doc complète (secrète, BACKEND ONLY, optionnelle).
  * `deploy-app/docker-compose.yml` : injection au service backend uniquement.
  * `deploy-app/install.sh` : warn non-bloquant si absente.
  * `frontend/src/pages/Events.jsx` : `catch` améliore le fallback (`setSmartResult(null)` → listing classique préservé).
- **Sécurité** : clé jamais dans le bundle React (grep frontend/src/ = 0), jamais dans les detail d'erreur (test anti-fuite dédié), backend only via `os.environ.get()`.
- **Découverte importante** : `emergentintegrations` appelle `load_dotenv()` à l'import → en dev/preview la clé est rechargée depuis `/app/backend/.env` même après `os.environ.pop`. En prod (container sans fichier .env), le fallback 503 se déclenchera correctement.
- **Tests** : 5/5 verts dans `test_v1rc4_smart_search_fallback.py` (dont subprocess isolé chdir `/tmp` pour reproduire vraiment l'absence de la clé).

## v1.0-rc4 · Vague 1 · stream_mode per-camera + diagnostic pipeline vidéo (2026-08)
- **Contexte** : ta Reolink 4K HEVC → ONVIF/RTSP/RTSP_URL OK mais Go2RTC échoue à décoder → preview KO. Fondations `MGVMS_AI_DIRECT_RTSP` + `ai_rtsp_url` existent depuis Session 10 v0.3, mais aucun choix explicite par caméra ni endpoint de diagnostic pointu.
- **Champ `Camera.stream_mode`** (defaut `auto` = comportement historique) :
  * `auto` : suit `MGVMS_AI_DIRECT_RTSP` global
  * `direct_rtsp` : IA ouvre RTSP en direct (indépendant de Go2RTC)
  * `go2rtc` : IA + preview passent par Go2RTC (streaming centralisé)
- **`ai_engine._sync_frame_source_workers`** : résolution du mode PER-CAMERA, `stream_mode` prime sur env global. Zéro régression pour les caméras sans le champ (defaults `auto`).
- **Nouvel endpoint** `GET /api/cameras/{id}/pipeline-diagnostic` (rôle technician+, lecture seule) qui teste 6 étapes séquencées :
  1. `rtsp_tcp_reachable` : socket TCP ip:rtsp_port
  2. `rtsp_stream_decodable` : ffprobe → codec/résolution/fps
  3. `go2rtc_api_reachable` : GET /api sur Go2RTC
  4. `go2rtc_stream_known` : cam_{id} déclaré ?
  5. `go2rtc_producer_alive` : producers actifs + medias publiés (⚠ WARN si producer sans media = pattern décodage HEVC échoué)
  6. `hevc_webrtc_compat` : décision statique H.265 → WebRTC direct impossible, preview via MJPEG
- **UI Cameras.jsx** :
  * Selector "Mode pipeline vidéo" dans le formulaire (auto / direct_rtsp / go2rtc)
  * Bouton icône 🩺 "Diagnostic pipeline vidéo" par caméra
  * Dialog dédié : verdict global (PASS/WARN/FAIL) + 6 étapes avec badges couleur + latence + détails dépliables
- **Tests** : 10/10 verts (`test_v1rc4_stream_mode_pipeline_diag.py`) + 5/5 lockout inchangés
- **Preuve UI** : screenshot dialog complet sur demo-cam-001 — 6 étapes affichées avec bons badges et détails techniques.
- **Ce que ça résout pour la Reolink** : quand tu lanceras ce diagnostic sur ta caméra 4K HEVC en prod, tu verras EXACTEMENT laquelle des 6 étapes échoue (probablement `go2rtc_producer_alive` en WARN avec "producer sans media publié" = hwaccel HEVC manquant côté ffmpeg go2rtc). C'est la data qu'il faut pour la Vague 3.

## v1.0-rc4.6 · Account lockout / brute-force protection par compte (2026-08)
- **Feature** : lockout PAR COMPTE, PERMANENT (5 échecs → locked, unlock explicite requis). Historique IP:email 15min conservé en défense en profondeur.
- **Backend** : nouveaux helpers atomiques `_account_track_failure` + `_account_track_success`. 7 nouveaux champs sur `users` (defaults sûrs, zéro migration). `public_user()` enrichi + `is_main_admin`.
- **Sécurité** : login sur compte locked → 401 générique (aucune fuite "existe / verrouillé"). Anti-énumération : email inconnu ne crée pas de doc.
- **Endpoint** : `POST /api/users/{id}/unlock` (admin) — refuse ADMIN_EMAIL avec 403 explicite pointant vers CLI.
- **CLI `mgvms_admin`** : `unlock-user <email>` et `list-locked`. Docker : `docker exec -it mgvms-backend python3 -m scripts.mgvms_admin <cmd>`.
- **UI Users** : badge rouge « Verrouillé » avec tooltip complet (locked_at + count + IP), bouton 🔓 unlock non-admin, icône 🔒 lecture seule pour admin principal.
- **Tests** : 5/5 verts (test_v1rc46_account_lockout.py).
- **Preuve** : admin locked + bon MDP → "Email ou mot de passe invalide" (screenshot). CLI unlock → HTTP 200 avec `last_login_ip` mis à jour.

## v1.0-rc4.3 · Build reproductibilité — Validation statique complète (2026-08)
- **Mémoire nettoyée** : `/root/.insightface`, `/root/.EasyOCR`, `/root/.paddlex`, `/root/.cache/*`, logs supervisor tronqués, `__pycache__` purgés, `git gc --aggressive`, vieux rapports Wave archivés dans `/app/memory/_archive.tar.gz`. Libéré : 9.2G → 8.3G (93% → 85%).
- **Méthode structurée** (fin des pytest chaotiques dans le pod preview) : validation statique dans le pod (Python 3.11 disponible dans `/root/.venv`), build Docker réel se fait sur la machine du client.
- **Validation 6/6 verte** :
  * `install.sh --check-only` : 0 erreur (13 fichiers, 233+17+25 lignes requirements 100 % épinglées, yarn.lock synchro)
  * `pip check` sur venv Python 3.11 : 0 requirement cassé
  * Assertion Dockerfile `contourpy==1.3.3` : OK
  * Assertion Dockerfile `cv2 4.10.0 + hasattr(cv2,'text')` : OpenCV contrib OK
  * Assertion Dockerfile `import fastapi, motor, cv2, litellm` : OK
  * Import `server.py` complet : 341 routes + WSDL 7/7 essentiels
- **Conclusion** : Dockerfile + docker-compose + requirements sont cohérents. Prêt pour `docker compose build` chez le client.

## v1.0-rc4.1 · Build reproductible (2026-06) — packaging only
- Yarn lock resync (react-window) → `--frozen-lockfile` + `yarn build` validés sur clone vierge.
- frontend/Dockerfile : --production=false + frozen-lockfile strict ; NODE_ENV non forcé (craco/visual-edits) ; DISABLE_ESLINT_PLUGIN au build (16 warnings métier pré-existants).
- backend/Dockerfile : chemins racine (context ..), plugins copiés, pip freeze --no-deps + extra-index emergentintegrations ; /.dockerignore racine créé.
- deploy-app/docker-compose.yml réécrit : healthchecks + depends_on healthy en cascade, storage /mnt/storage/*, GPU conservé, demo-media conservé ; doublons /docker supprimés ; .env.example complet.
- Validé : compose config (binaire v2.39.1 réel), 245/245 pins x86_64 dispo. NON testable ici : docker build/up (pas de daemon) — checklist serveur dans deploy-app/README.md.
- Rapport 25 points : deploy-app/RAPPORT_BUILD_v1.0-rc4.md

## v1.0-rc4.2 · install.sh (2026-06)
- deploy-app/install.sh : pull GitHub + 26 validations pré-vol (Dockerfiles/compose/requirements×3/yarn.lock sync) + mkdir /mnt/storage + .env + build/up + attente healthchecks. Options --no-pull/--check-only/--no-cache. Testé nominal + négatif.
