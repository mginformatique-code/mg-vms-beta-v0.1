# MG-VMS — Product Requirements Document

## Implemented (2026-07)
- ✅ **SPRINT P0 — Stabilisation caméra & audit sandbox (2.4.0 — 2026-07-21)**
  - **Root cause du ping-pong Connect/Disconnect identifiée et fixée** : `_probe_status_once` appelait `register_camera_stream` toutes les 30 s → DELETE + PUT sur le flux go2rtc → tous les consommateurs (browser MJPEG, recorder ffmpeg, IA) étaient déconnectés en boucle. Corrigé : la sonde périodique vérifie désormais `/api/streams` (READ-ONLY) et ne (ré-)enregistre que si le flux a réellement disparu.
  - **Un seul décodage par caméra** : suppression du producteur redondant `ffmpeg:<name>#video=mjpeg` dans le flux principal (`register_camera_stream` + `go2rtc.yaml` démos). Chaque flux a désormais un **producteur unique** ; les consommateurs MJPEG (Live, snapshot, IA) utilisent la conversion à la demande de go2rtc → pipeline partagé Live/Recording/IA/ALPR.
  - **Nettoyage automatique des flux temporaires** `probe_*` au démarrage du backend (résidus des tests de connectivité qui étaient persistés dans `go2rtc.yaml`).
  - **Audit sandbox #11** — suppression de tous les éléments de démonstration/fake :
    - `POST /api/anpr/detect` (endpoint qui injectait des plaques fictives) → supprimé
    - Bouton « Simuler une détection » (ANPR) → retiré de l'UI
    - Bouton « Simuler une alerte critique » (Alerts) → retiré (générait un alert `Intrusion détectée — zone périmètre` fictif)
    - Badges UI trompeurs `hw.simulated` (Hardware) et `net.simulated` (Network) → remplacés par état réel (« Aucun GPU détecté » quand la liste est vide) ou retirés
    - Commentaires backend « Sandbox : flux/lecture simulés » sur `/recordings/timeline` corrigés — les enregistrements sont 100 % réels (MP4 sur disque)
  - Vérifié via `ps -ef` + `/api/streams` : 1 seul ffmpeg par flux, 0 producer doublon, aucun churn pendant 65 s d'observation.


## Original problem statement
Plateforme professionnelle de vidéosurveillance (concurrent de Milestone, Genetec, Nx Witness, UniFi Protect). Cible: collectivités, mairies, entreprises, industries, sites sensibles, parkings. 100% web, responsive, multi-sites, IA (YOLO/ANPR), tracking, alertes, RBAC, monitoring, etc.

## Stack reality (this environment)
React + FastAPI + MongoDB (Kubernetes single backend/frontend). Note: the requested multi-container Docker (Vue/PostgreSQL/Celery/GPU-YOLO/RTSP ingestion) is not supported in this sandbox; the platform is built modularly on the supported stack and maps to that production architecture later.

## User personas
- Administrateur: gestion complète (utilisateurs, sites, caméras, suppression)
- Technicien: gestion sites/caméras/listes
- Client: consultation, PTZ, acquittement alertes
- Lecture seule / Invité: consultation restreinte

## Core requirements (static)
1. Auth JWT + RBAC (5 rôles) + 2FA TOTP
2. Multi-sites
3. Caméras (RTSP/ONVIF config, test connexion, snapshot, PTZ)
4. Live View mur vidéo (1→64)
5. Dashboard pro (stats système, graphiques)
6. ANPR + recherche véhicule + listes blanche/noire + IA vision
7. Alertes + Audit + Carte OSM
8. Bilingue FR/EN, thème clair/sombre

## Implemented (2026-07)
- ✅ **CAMERA MANAGEMENT PRO (2.3.0 — 2026-07-21)**
  - **Mode ONVIF** : plus jamais d'URL RTSP demandée manuellement. Workflow complet : IP + port + user + pass → `GetProfiles` → `GetStreamUri` → **choix de profil (Main / Sub / 3ᵉ)** → enregistrement auto go2rtc → caméra créée. RTSP totalement transparent.
  - **Mode RTSP manuel avec Assistant** : 25 fabricants supportés (Reolink, Hikvision, Dahua, Axis, Hanwha, Uniview, Bosch, Vivotek, TP-Link VIGI, UniFi Protect, Milesight, Provision-ISR, Avigilon, Tiandy, Hik-OEM, Annke, Ezviz, Amcrest, Foscam, ACTi, GeoVision, Panasonic, Sony, Pelco, Générique). Choix fabricant → modèle → flux (main/sub/main_h264/sub_h265/…) → canal → **URL générée automatiquement**. Champ RTSP toujours modifiable manuellement.
  - **Bibliothèque extensible** `/app/backend/camera_profiles.json` : ajouter un nouveau fabricant ne nécessite aucune modification de code (recharge à chaque requête `GET /api/cameras/brands`).
  - **Encodage automatique des credentials** : `# @ + : espace /` sont automatiquement URL-encodés (RFC 3986) à la fois par `_build_rtsp_url` (côté serveur) et par `POST /api/cameras/generate-rtsp-url`. L'utilisateur peut coller n'importe quel mot de passe.
  - **Bouton « Détecter automatiquement »** (`POST /api/cameras/auto-detect`) : un clic → fabricant, modèle, firmware, PTZ, profils, URI RTSP, résolution effective (ffprobe). TCP pré-check 3 s pour fail-fast.
  - **Test de connexion 7 étapes** avec statut ✅/⚠️/❌ par étape : `ping` · `onvif_port` · `onvif_auth` · `rtsp_port` · `rtsp_open` · `go2rtc` · `preview` + **aperçu vidéo JPEG** live dans le dialog.
  - **Édition complète** : modif de nom, IP, protocole, ports, credentials, profil vidéo, URL RTSP, résolution, fps, bitrate, paramètres IA, paramètres d'enregistrement. `PUT /api/cameras/{id}` recharge automatiquement go2rtc sans supprimer la caméra. Password laissé vide = conserve l'ancien.
  - **Priorité** : ONVIF auto → RTSP généré via assistant → saisie manuelle en dernier recours (comme demandé).
  - Ordre d'inclusion des routers corrigé (`stream_router` avant `api_router`) pour que `/api/cameras/brands`, `/generate-rtsp-url`, `/auto-detect` ne soient plus interceptés par `/api/cameras/{id}`.

## Implemented (2026-07)
- ✅ **PRODUCTION READINESS #2 — Modes RTSP/ONVIF séparés (2.2.0 — 2026-07-21)**
  - **CameraInput** gagne un champ `mode` (`rtsp` | `onvif`). Frontend : toggle « Mode RTSP » / « Mode ONVIF » en haut du dialog, avec bascule des champs affichés.
  - **Mode RTSP** : valide seulement Port RTSP + URL RTSP (ffprobe).
  - **Mode ONVIF** : valide seulement Port ONVIF + identifiants ONVIF. L'URL RTSP est **auto-découverte** via `GetStreamUri` sur le premier profil, puis registrée dans go2rtc. Aucune saisie RTSP requise.
  - `POST /api/cameras/test-connectivity` désormais mode-aware.
  - `POST /api/cameras` et `PUT /api/cameras/{id}` supportent les deux modes ; TCP pré-check ONVIF (fail-fast 3 s) pour éviter les timeouts SOAP sur hôtes injoignables.
  - **Édition de caméra** : bouton crayon dans la liste, dialog partagé qui accepte modification de nom, IP, protocole, ports, credentials, URL RTSP, enregistrement, IA. `PUT` recharge automatiquement la config go2rtc.
  - **Live vidéo stable** : `<img>` MJPEG (via go2rtc) avec reconnexion automatique (backoff 2.5 s) au lieu de tomber sur « No Signal ». Le RTSP brut n'est JAMAIS exposé au frontend — seulement `live.mjpeg`/`frame.jpeg` du backend proxy.
  - **IA logs clairs** : chaque cycle et chaque caméra loggue `IA · <name> (<id>) : N détection(s) [Personne:0.53, ...] · mouvement=X% · N plaque(s)` dans `backend.err.log`.
  - **Dépendances propres** : `litellm` (URL customer-assets) et `emergentintegrations` retirés de `requirements.txt`. Endpoint `/api/ai/analyze-plate` réécrit avec le pipeline **local** (`fast-alpr` + YOLO) — zéro cloud, zéro clé LLM. Dockerfile backend nettoyé (plus de `--extra-index-url`). `docker compose up --build` fonctionne depuis un clone propre.

## Implemented (2026-06)
- ✅ **PIPELINE CAMÉRA RÉEL / PRODUCTION (2.1.0 — 2026-07-20)** : (1) enregistrement auto dans go2rtc après POST/PUT `/api/cameras` + vérification `/api/streams` avant retour succès ; rollback DB (HTTP 400) si go2rtc refuse. (2) `CameraInput` ajoute `rtsp_port` (554) et `onvif_port` (80) configurables. (3) `POST /api/cameras/test-connectivity` : TCP ping IP:rtsp_port + IP:onvif_port + ffprobe RTSP (résolution/fps/codec). Sauvegarde bloquée côté UI si test KO. (4) `camera_status_loop` (30 s) : statut Online/Offline reflète l'état RÉEL du flux (frame JPEG lisible). (5) recorder : `stop_all_recorders()` au shutdown + `sweep_orphan_recorders()` au démarrage. (6) Login : plus de pré-remplissage ni bloc identifiants démo. (7) Branding Emergent supprimé (title = `MG-VMS`, meta description, script emergent-main.js retiré). Backend pytest 9/9 + frontend Playwright 100% (itération 15).
- ✅ PERMISSIONS GRANULAIRES (2.0.0) : par-utilisateur, gérées **uniquement par admin** — view_live, view_recordings, read_plates, stream_hd (HD/SD), ptz_control, export_files. `require_permission` appliqué sur les endpoints concernés ; éditeur de permissions dans `/users` + masquage nav. Tests 22/22 backend + frontend 100% (itération 11).
- ✅ RESSOURCES MATÉRIELLES CPU/GPU — Phase 1 (1.9.0) : module `/hardware` 4 onglets — détection réelle CPU/RAM + **4 GPU simulés** + accélérateurs ; allocation par fonction (10) ; profils (Éco/Équilibré/Perf/Ultra/Custom) + priorités par moteur + auto-optimize ; **monitoring temps réel** (poll 2s, CPU/GPU/VRAM/temp/conso/IA/FFmpeg). Endpoints info/config/monitor/profile (writes admin). Tests 17/17 backend + frontend 100% (itération 10). Reste Phase 2 (auto-optimisation + historique) & Phase 3 (pools GPU, benchmarks, /deploy).
- ✅ RAPPORTS + ANPR ENRICHI + POLL RÉSEAU (1.8.0) : module **Rapports** `/reports` (CSV/Excel/PDF × plaques/events/alertes/équipements, filtres date+site) ; alerte liste noire **enrichie** (photo véhicule + lien caméra Discord/Telegram, deep-link `/recordings?camera=`) ; **poll réseau périodique** serveur (30s) avec alertes temps réel + auto-refresh UI. Tests 25/25 backend + frontend 100% (itération 9).
- ✅ EXPORT DE SÉQUENCE (1.7.0) : depuis la timeline `/recordings`, sélection de plage (glisser + champs) → **ZIP réel** téléchargeable (manifeste + vignettes) ; **MP4 mis en file** (généré en prod FFmpeg). Endpoints export/list/download + endpoint prod `POST /export` (concat FFmpeg) dans `/deploy/recording`. Testé curl + screenshot.
- ✅ SUPERVISION RÉSEAU (1.6.0) : module `/network` — inventaire (switch/routeur/NAS/UPS/serveur/NVR), **topologie** SVG, fiche équipement, ICMP/SNMP **simulé** (ping/poll) + alertes auto (hors-ligne / UPS batterie). Artefacts prod `/deploy/network-monitor` (pysnmp+ICMP) + table `equipment`. Tests 12/12 backend + frontend 100% (itération 8).
- ✅ CŒUR VIDÉO P0 + TIMELINE (1.5.0) : artefacts prod `/deploy/ai-engine` (YOLOv11+ByteTrack `worker.py`, ANPR réel `anpr.py`), `/deploy/recording/recorder.py` (MP4+MinIO+timeline+rétention), cœur ffmpeg complété (stream_manager/onvif/go2rtc) — NON exécutables ici. Sandbox : page **Enregistrements & Timeline** (`/recordings`) + endpoints `GET /api/recordings/timeline` & `/playback`, seed idempotent. Testé curl + screenshot.
- ✅ SPRINT 3 PLUGINS + ANPR LISTE NOIRE AUTO + ARTEFACTS /deploy : socle de plugins (10 modules, activation dynamique, page admin), alerte auto sur plaque liste noire (POST /api/anpr/detect + analyze-plate → alerte critique + WebSocket + notifications), rate-limit login assoupli (30/min). Artefacts prod /deploy (docker-compose micro-services, Dockerfiles, schéma PostgreSQL+SQLAlchemy+Alembic, Prometheus/Grafana/Loki, K8s) — NON exécutables ici. Tests 14/14 backend + frontend 100% (itération 7).
- ✅ SPRINT 2 TEMPS RÉEL (P1) : WebSocket /api/ws (auth token + cloisonnement site) push métriques (5s) + alertes live ; métriques système réelles (psutil) ; pagination serveur (offset/limit + X-Total-Count, réponses restent des listes) + UI « Charger plus » (ANPR, Audit) ; indicateur LIVE + toasts temps réel. Tests 42/42 backend + frontend 100% (itération 6).
- ✅ SPRINT 1 SÉCURITÉ (P1) : anti brute-force (lockout 15min/5 essais), rate-limiting auth, reset password (jeton TTL usage unique), en-têtes OWASP, CORS restreint, cloisonnement par site (allowed_sites/site_scope), refresh token câblé front, affectation des sites par utilisateur. Tests 17/17 backend + frontend OK (itération 5).
- ✅ Notifications/Intégrations: page de config SMTP + Discord + Telegram (saisie admin), secrets chiffrés (Fernet) + masqués en lecture, test d'envoi par canal, activation/désactivation par canal, envoi auto sur alertes critiques (BackgroundTasks). POST /api/alerts déclenche la dispatch. Tests: backend 20/20, frontend 14/14.
- ✅ JWT Bearer auth, RBAC require_role, 2FA TOTP (setup/verify/disable), admin+3 demo users seeded
- ✅ Sites CRUD, Cameras CRUD + test/snapshot/PTZ endpoints (simulated)
- ✅ Live View video wall with 1/4/9/16/25/36/49/64 layouts
- ✅ Dashboard KPIs + 24h activity area chart + detection pie + system health
- ✅ ANPR plate search w/ filters, CSV export, watchlist, AI image analysis (OpenAI gpt-5.4 via emergentintegrations)
- ✅ Vehicle search (plate/color/make/type/site/direction/date)
- ✅ Alerts center (ack), Audit log, OpenStreetMap map view
- ✅ Users management, Settings (theme/lang/2FA)
- ✅ Bilingual FR/EN, dark/light themes — control-room design
- Tested: backend 30/30, frontend flows 100%

## Backlog (prioritized)
- P1: Real RTSP/WebRTC streaming, ONVIF auto-discovery, real YOLOv11 detection + ByteTrack/DeepSort tracking
- P1: Recordings timeline + MP4/AVI/JPEG/ZIP export, storage backends (NAS/SMB/NFS/S3/MinIO)
- P2: Alert channels (Email/Telegram/Discord/Webhook/MQTT/SMS), PDF/Excel reports
- P2: Floor plans with camera placement, Prometheus/Grafana monitoring, backup/restore
- P3: Facial recognition, thermal, drone, plugins/marketplace, mobile apps

## MOCKED / SIMULATED
- Camera live streams (placeholder images), test-connection & snapshot results, system CPU/RAM metrics, seeded demo events/plates/alerts. AI ANPR uses a real LLM call.

## Next tasks
- Wire real video ingestion pipeline (separate worker/ffmpeg service in production compose)
- Add alert notification channels + reports module

## Session 2026-06 (fork) — Stack de production /deploy complétée
Demande utilisateur : (1) architecture propre complète dans /deploy, (2) frontend Vue 3 + Vite + TS pour /deploy, sans toucher au code sandbox, suppression des références "emergent".
- ✅ /deploy/api/ : API FastAPI complète — SQLAlchemy 2.0 async (psycopg3) + Alembic (migrations auto au boot) + PostgreSQL + Redis + Celery (worker+beat). 17 modules : auth (JWT httpOnly + refresh + brute-force + reset), users (matrice permissions), organizations, sites, cameras (ONVIF/PTZ délégués au service ffmpeg), streams (WebRTC/HLS go2rtc, dégradation SD si !stream_hd), recordings (timeline), playback (URLs signées S3/MinIO), events (WS temps réel via Redis pub/sub), ai (règles + recherche plaques + analytics), notifications, maps, storage, monitoring (stats + métriques Prometheus), audit, settings, health. Versions verrouillées testées en venv propre (50 routes importées OK).
- ✅ /deploy/notification/ : service consommant la file Redis mgvms:notifications → Email SMTP / Discord / Telegram / Webhook.
- ✅ /deploy/frontend/ : Vue 3.5 + Vite 6 + TypeScript + Pinia + vue-router. 8 vues (Login, Dashboard temps réel WS, Caméras CRUD, Direct+PTZ+badge SD, Enregistrements+export, Événements+ack, Utilisateurs avec matrice de permissions, Paramètres/canaux notif). Build + vue-tsc : 0 erreur. Dockerfile multi-étapes Node20→Nginx.
- ✅ Zéro référence "emergent" dans /deploy et /deploy-app (EMERGENT_LLM_KEY supprimée). NB : dans /deploy-app, l'analyse LLM ANPR de la démo ne fonctionnera pas sans clé (feature mock).
- ✅ Nettoyage : /deploy/db/ supprimé (doublon) — source de vérité = api/app/models.py + api/alembic. Compose corrigé (commande celery app.tasks.celery_app, plus de schema.sql initdb). README /deploy réécrit (Windows/WSL2 + Linux, choix techniques justifiés).
- ✅ Sandbox intacte (env pip restauré après incident d'auto-install, backend+frontend vérifiés OK).
- NB sandbox : le code démo (/app/backend, /app/frontend) utilise toujours la clé LLM pour l'ANPR mock — inchangé volontairement.

## Prochaines étapes proposées
- Tester la stack /deploy chez l'utilisateur (docker compose up) et corriger les retours
- Enrichir le frontend Vue (recherche LAPI, timeline enregistrements, cartes/plans)
- Optimisation auto ressources matérielles Phase 2 (sandbox)
- ✅ Frontend Vue /deploy : vue « Recherche LAPI » ajoutée (filtres plaque/site/liste/dates, photos, badges liste noire/blanche, garde route+nav via permission read_anpr). Build + vue-tsc OK.
- ✅ Frontend Vue /deploy : timeline 24h des enregistrements dans RecordingsView (sélecteur caméra + date, segments positionnés, hover détail, clic → URL de lecture signée). Build + vue-tsc OK.
- ✅ Bugfix VPS utilisateur (erreur ajv au build Docker frontend) : cause = ancienne copie du repo avec Dockerfile npm. Dockerfile actuel (Yarn + yarn.lock) durci avec --frozen-lockfile ; build à froid reproduit et validé par testing_agent (iteration_12, 100%). Section Dépannage ajoutée à deploy-app/README.md.

## Session 2026-07 — Passage au 100% RÉEL (plus aucune donnée factice)
- ✅ Vidéo live réelle : go2rtc (binaire persistant /app/go2rtc/go2rtc, supervisor) + proxys authentifiés /api/stream/{id}/live.mjpeg & frame.jpeg (?token=). 2 caméras démo à flux H.264 réels (mire + scène de rue). Test caméra = frame réelle + ffprobe (résolution/fps/codec). Découverte ONVIF réelle (WS-Discovery + onvif-zeep) + UI dans Caméras.
- ✅ Purge de toutes les données factices (seed.py: flag purged_fake_data_v1). Équipements réseau: ping ICMP réel (icmplib). Matériel: psutil réel, GPU réels uniquement (nvidia-smi). Dashboard timeseries: agrégations Mongo réelles.
- ✅ Enregistrement réel : recorder.py (FFmpeg segments 120s → /data/recordings, RECORDINGS_DIR env), indexation Mongo, rétention 7j, garde-fou espace disque (2 Go min), relecture <video> réelle (/api/recordings/{id}/media?token=), export ZIP (vrais MP4) + MP4 (concat FFmpeg).
- ✅ IA réelle : ai_engine.py — YOLO yolo11n CPU (événements Personne/Voiture/... avec vignettes base64, couleur réelle des véhicules par analyse HSV), détection de mouvement réelle (diff d'images, motion_pct), LAPI locale fast-alpr (modèle plaques européennes) avec vehicle_type/color associés, alertes liste noire.
- ✅ Scénarios d'alertes IA (7, configurables via GET/PUT /api/ai/alert-rules + dialog 'Règles IA' page Alertes) : intrusion_nocturne, vol_vehicule, rodeur, attroupement, vive_allure, collision (accident), enfant_route. Alertes réelles avec vignette + WebSocket + notification.
- ✅ Nouvelle page 'Événements IA' (/events) : cartes avec vignette/type/confiance/couleur/horodatage + filtres. Corrélation segments ↔ événements (mode ai/motion/continuous dans la timeline de relecture).
- ✅ Recherche véhicule : recherche auto (debounce), 13 couleurs, filtre insensible à la casse.
- ✅ deploy-app mis à jour : service go2rtc + ffmpeg dans l'image backend + vidéo démo montée.
- Incidents résolus : disque /app plein (stockage déplacé /data), ffmpeg/go2rtc effacés par reset d'env (binaires statiques persistants dans /app/bin et /app/go2rtc + PATH dans server.py), ffmpeg héritant du socket uvicorn 8001 (close_fds/start_new_session).
- Tests : iteration_13 (système réel, 13/14) et iteration_14 (couleurs + scénarios IA, 100%).

## Backlog P1/P2
- P1 : plaques make/model (modèle dédié), WebRTC faible latence dans l'UI (actuellement MJPEG), page plans de sites (frontend Vue /deploy), PTZ ONVIF réel (relais continuous move)
- P2 : SNMP UPS réel, optimisation auto CPU/GPU, refactoring routers.py en modules
