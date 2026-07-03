# CHANGELOG — MG-VMS

Format inspiré de Keep a Changelog. Dates au format AAAA-MM.

## [2.0.0] — 2026-06 — Permissions granulaires par utilisateur (gérées par admin)
### Ajouté
- **Permissions granulaires** par utilisateur (en plus des rôles), **gérées uniquement par l'admin** : `view_live`, `view_recordings`, `read_plates`, `stream_hd`, `ptz_control`, `export_files`. Admin = bypass (toutes accordées). Défauts par rôle + overrides par utilisateur (`effective_permissions`).
- Backend : `require_permission(perm)` (auth.py) appliqué sur snapshot/stream (view_live), qualité **HD/SD** (`GET /api/cameras/{id}/stream`, stream_hd), recordings timeline+playback (view_recordings), `/plates`+`/anpr/detect` (read_plates), PTZ (ptz_control), recordings/plates export (export_files). `permissions` exposé dans `/auth/me` et `/users`.
- Gestion utilisateur réservée admin (déjà le cas) : création/édition incluent un éditeur de **permissions** (UserCreate/UserUpdate + `_clean_permissions`).
- Frontend : `hasPerm()` (AppContext), **dialog de permissions** par utilisateur dans `/users` (6 bascules), masquage de la navigation (Live/Enregistrements/ANPR/Véhicules) selon les permissions. **Live View** : contrôles PTZ masqués sans `ptz_control`, badge **HD/SD** selon `stream_hd` ; **panneau d'export** masqué sans `export_files`.
### Tests
- Backend 22/22 (test_permissions.py), frontend 100% (gating nav, éditeur de perms, persistance, bypass admin). Itération 11.

## [1.9.1] — 2026-06 — Déploiement Docker testable (app réelle) + compose prod cohérent
### Ajouté — `deploy-app/` (test Docker fonctionnel)
- `docker-compose.yml` : MongoDB + **backend FastAPI** (`backend/Dockerfile`, python:3.11-slim, extra-index pour emergentintegrations) + **frontend React/Nginx** (`frontend/Dockerfile` multi-stage node:20 → nginx, `nginx.conf` SPA) → `docker compose up -d --build` lance MG-VMS complet (http://localhost:3000, API :8001).
- `.env.example` (DB_NAME, CORS_ORIGINS, JWT_SECRET, ADMIN_*, REACT_APP_BACKEND_URL, EMERGENT_LLM_KEY) + `README.md` (démarrage, commandes, notes domaine/CORS). `.dockerignore` backend & frontend.
### Vérifié
- Compose YAML valide, contextes de build résolus, tous les Dockerfiles/nginx.conf présents, gestion env OK. ⚠️ **Non exécuté dans le sandbox** (pas de Docker) — à lancer sur la machine de l'utilisateur.
- Compose production `/deploy` (18 services) revalidé : YAML OK, tous les contextes de build ont un Dockerfile. Pointeur ajouté vers `deploy-app/` pour le test rapide.

## [1.9.0] — 2026-06 — Ressources matérielles CPU/GPU (Phase 1)
### Ajouté
- **Module Ressources matérielles** (`/hardware`, technician+ en lecture, admin en écriture) — 4 onglets :
  - **Matériel** : détection réelle CPU (cœurs/threads, psutil) + RAM ; inventaire **GPU** (RTX 4070, RTX A2000, Intel UHD/QuickSync, Google Coral) **simulé** en sandbox (détection réelle nvidia-smi en prod) + matrice d'accélérations (CUDA/NVENC/NVDEC/TensorRT/QuickSync/OpenVINO/OpenCL/DirectML/Vulkan/EdgeTPU).
  - **Ressources** : allocation du composant (CPU/GPU/NVDEC/NVENC/QuickSync/AMF/Auto/Coral…) pour 10 fonctions (décodage, encodage, Live, relecture, IA, ANPR, miniatures, export, PDF, reconversion).
  - **Profils & priorités** : profils Économie/Équilibré/Performance/Ultra/Personnalisé (pré-configurent les allocations) + priorités par moteur (Temps réel/Normale/Basse) + bascule Optimisation automatique.
  - **Monitoring** temps réel (poll 2s) : CPU/RAM/charge IA/FFmpeg, flux/FPS/consommation/températures, et par GPU util/VRAM/temp/conso/ventilateur (code couleur).
- Endpoints : `GET /api/hardware/info|config|monitor`, `PUT /api/hardware/config` (admin), `POST /api/hardware/profile/{p}` (admin). Toute modif manuelle bascule en profil « custom ». Détection au démarrage (`seed_hardware`).
### Tests
- Backend 17/17 (test_hardware.py), frontend 100% (4 onglets, RBAC admin/tech/viewer, monitoring live). Itération 10.
### À venir
- Phase 2 : moteur d'auto-optimisation (règles de bascule GPU↔CPU), historique + graphiques + alertes (temp/VRAM/GPU indispo).
- Phase 3 : Pools GPU (mode entreprise), GPU par caméra, benchmarks (décodage/encodage/IA/lecture/export), matrice de compatibilité étendue. Artefacts prod `/deploy` (pynvml/NVENC/OpenVINO/Coral).

## [1.8.0] — 2026-06 — Rapports + Alerte ANPR enrichie + Poll réseau périodique
### Ajouté
- **Module Rapports** (`/reports`, role technician+) : génération CSV / Excel (openpyxl) / PDF (reportlab) pour 4 jeux — plaques ANPR, événements IA, alertes, équipements réseau. Filtres plage de dates + site (cloisonnés). Endpoints `GET /api/reports/types` et `GET /api/reports/{type}?format=&site_id=&date_from=&date_to=`.
- **Alerte « liste noire » enrichie** : les notifications Discord (embed avec **photo véhicule** + champ lien) et Telegram (sendPhoto + caption avec **lien caméra**) incluent désormais l'image et un lien profond `/recordings?camera=<id>`. `send_notification(subject, body, image_url, link_url)`. La page Recordings présélectionne la caméra depuis `?camera=`.
- **Poll réseau périodique côté serveur** : `network_poll_broadcaster` (intervalle `NETWORK_POLL_INTERVAL`, défaut 30s) sonde l'inventaire (simulé), met à jour statut+latence et **lève des alertes de transition** diffusées en temps réel (WebSocket). La page `/network` se rafraîchit automatiquement toutes les 30s.
### Tests
- Backend 25/25 (test_reports_sprint.py : 3 formats × 4 types, filtres, 403 viewer, alerte blacklist enrichie sans erreur), frontend 100% (nav role-gating, téléchargements, deep-link caméra). Itération 9.

## [1.7.0] — 2026-06 — Export de séquence vidéo (timeline → ZIP/MP4)
### Ajouté — Sandbox
- **Export de séquence** depuis la timeline (`/recordings`) : sélection de plage par **glisser sur la timeline** (surbrillance) + champs début/fin + choix de format. **ZIP réel téléchargeable** (manifeste JSON + README + vignettes des segments de la plage). **MP4 mis en file**, marqué « généré en production (FFmpeg) ». Liste des **exports récents** avec statut (Prêt/En file) et téléchargement.
- Endpoints : `POST /api/recordings/export`, `GET /api/recordings/exports`, `GET /api/recordings/exports/{id}/download` (ZIP streamé via zipfile, cloisonné par utilisateur/site).
### Ajouté — Artefacts production `/deploy`
- `recording/recorder.py` : endpoint `POST /export` (concat FFmpeg `-f concat -c copy` → MP4, ou ZIP des segments bruts) → upload MinIO/S3 + URL présignée.
### Tests
- Backend testé curl (ZIP 194Ko vérifié : manifest+thumbnails ; MP4 queued ; list), frontend vérifié (drag-select + export + exports récents).

## [1.6.0] — 2026-06 — Supervision réseau (SNMP/ICMP) + topologie
### Ajouté — Sandbox (MongoDB)
- **Module Supervision réseau** (`/network`, visible dès le rôle client) : inventaire d'équipements (Switch/Routeur/NAS/UPS/Serveur/NVR/Caméra/Générique), **carte de topologie** hiérarchique (SVG, liens parent/enfant up/down colorés par statut), vue tableau, **fiche équipement** (statut, latence, uptime, fabricant, modèle, IP, site ; UPS : batterie/sur batterie/autonomie).
- **ICMP/SNMP simulé** : `POST /api/network/equipment/{id}/ping` et `POST /api/network/poll` (sweep) mettent à jour statut + latence ; **alerte critique automatique** sur passage hors-ligne ou UPS sur batterie (réutilise broadcast WebSocket + notifications).
- Endpoints `network.py` : `GET /api/network/equipment|stats|topology|equipment/{id}`, `POST/PUT/DELETE /api/network/equipment`, `POST /api/network/{id}/ping`, `POST /api/network/poll`. Cloisonnement par site appliqué. Seed idempotent (routeur+UPS+switch+NAS+NVR+serveur par site).
### Ajouté — Artefacts production `/deploy`
- `network-monitor/` : `poller.py` (ICMP réel + SNMP UPS-MIB/IF-MIB via pysnmp, alertes), `Dockerfile` (iputils-ping + NET_RAW), `requirements.txt` ; service ajouté au `docker-compose.yml` ; table `equipment` (avec topologie `parent_id`) ajoutée au `schema.sql`.
### Tests
- Backend 12/12 (pytest test_network.py), frontend 100% (topologie, CRUD, ping/poll, fiche UPS, cloisonnement viewer). Itération 8.

## [1.5.0] — 2026-06 — Cœur Vidéo P0 (artefacts /deploy) + Timeline d'enregistrements (sandbox)
### Ajouté — Artefacts production `/deploy` (NON exécutables ici)
- **Moteur IA** `/deploy/ai-engine/` : `worker.py` (YOLOv11 Ultralytics + tracking ByteTrack, dédup par piste, écriture `events`, Redis Pub/Sub) ; `anpr.py` (LAPI réelle via fast-alpr → `plates` + alerte critique liste noire) ; `requirements.txt`.
- **Service d'enregistrement** `/deploy/recording/recorder.py` : segmentation MP4 FFmpeg, upload MinIO/S3, indexation `recordings`, API timeline + URL présignée de lecture, rétention/quota.
- **Cœur vidéo ffmpeg** complété : `stream_manager.py` (RTSP→HLS + reconnexion + snapshot + WebRTC go2rtc), `onvif_discovery.py` (WS-Discovery + profils média), `go2rtc.yaml`.
- Correction du conflit de dépendance `ffmpeg/requirements.txt` (httpx 0.26→0.28.1).
### Ajouté — Incrément testable (sandbox, MongoDB)
- **Page Enregistrements & Timeline** (`/recordings`) : sélection caméra + date, timeline 24h colorée par mode (continu/mouvement/IA), marqueurs d'événements, lecteur (lecture simulée), liste de segments, stats (couverture/volume/segments/événements).
- Endpoints `GET /api/recordings/timeline` et `GET /api/recordings/{id}/playback` (cloisonnés par site) ; seed idempotent de segments sur 3 jours.
### Tests
- Backend testé (curl e2e : timeline + playback OK), frontend vérifié (screenshot, lecture d'un segment).

## [1.4.0] — 2026-06 — Sprint 3 : Plugins + ANPR liste noire auto + Artefacts /deploy
### Ajouté
- **Socle d'architecture de plugins** : registre de 10 modules (ANPR cœur, IA YOLO, tracking, reconnaissance faciale, parking, thermique, radar, drone, MQTT, contrôle d'accès), activation/désactivation dynamique persistée (`GET/PUT /api/plugins`), page UI Plugins (admin), protection des plugins cœur.
- **Alerte automatique « plaque liste noire »** : `POST /api/anpr/detect` + `analyze-plate` déclenchent une alerte critique + broadcast WebSocket + dispatch notifications quand la plaque est en liste noire. Simulateur de détection sur la page ANPR.
- **Artefacts de production `/deploy`** (NON exécutables ici) : `docker-compose.yml` micro-services, `Dockerfile`s (api, frontend, ai-engine GPU, ffmpeg, recording, notification, backup), schéma **PostgreSQL** optimisé (index GIN trigram, partitions), **SQLAlchemy** + **Alembic**, configs **Prometheus/Grafana/Loki/Alertmanager**, manifests **Kubernetes** (Deployments, StatefulSet PG, Ingress WebSocket, HPA), README d'architecture.
### Modifié
- Rate-limit `/auth/login` assoupli (30/min) pour les IP partagées ; la protection anti brute-force reste le verrouillage après 5 échecs/compte.
### Tests
- 14/14 Sprint 3 backend + frontend 100% (itération 7).

## [1.3.0] — 2026-06 — Sprint 2 : Temps réel (P1)
### Ajouté
- **WebSocket** `/api/ws` (authentifié par token, cloisonné par site) : push live des **métriques système** (toutes les 5s) et des **alertes** (à la création). Reconnexion auto côté front.
- **Métriques système réelles** via **psutil** dans `/api/dashboard/stats` (CPU/RAM/stockage/température/bande passante/uptime) — remplacent les valeurs aléatoires.
- **Pagination serveur** non-cassante sur `/plates`, `/events`, `/alerts`, `/audit` : params `limit`/`offset` + header `X-Total-Count` (le corps reste un tableau JSON). UI « Charger plus » sur ANPR et Audit.
- **Front** : indicateur « LIVE » (topbar), toasts d'alerte temps réel, badge d'alertes live, rechargement auto du dashboard/alertes sur nouvelle alerte.
- `POST /api/alerts` : `broadcast_alert` ; `site_id` désormais honoré (alerte rattachable à un site sans caméra) ; `test_camera` diffuse le changement de statut.
### Tests
- 12/12 Sprint 2 + 30/30 régression = **42/42 backend**, frontend 100% (itération 6).

## [1.2.0] — 2026-06 — Sprint 1 : Sécurité (P1)
### Ajouté
- **Anti brute-force** : verrouillage du compte 15 min après 5 échecs (clé IP:email, collection `login_attempts`), HTTP 423.
- **Rate-limiting** des endpoints sensibles (`/auth/login` 10/min, `/auth/forgot-password` 5/5min, `/auth/reset-password` 10/5min), HTTP 429 + `Retry-After`.
- **Reset password** : `POST /auth/forgot-password` (réponse générique anti-énumération) + `POST /auth/reset-password` (jeton `secrets`, TTL 1h, usage unique), envoi best-effort par SMTP si configuré.
- **En-têtes de sécurité OWASP** sur toutes les réponses (X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy, X-XSS-Protection) via `SecurityMiddleware`.
- **Cloisonnement par site** : helpers `allowed_sites()` / `site_scope()` appliqués à sites, caméras, événements, plaques, alertes et dashboard. `site_ids` assignables par l'admin (UI Users + `PUT /users/{id}`).
- **Refresh token câblé** côté frontend : intercepteur axios qui rafraîchit l'access token sur 401 et rejoue la requête ; stockage `mg_refresh`.
- **Frontend** : flux « Mot de passe oublié », page `/reset-password`, dialog d'affectation des sites par utilisateur.
### Modifié
- **CORS** restreint à l'origine explicite du frontend (au lieu de `*`).
- Cookie `access_token` passé en `secure=True`.
- Seed : `client` rattaché au 1er site, `viewer` au 2e (démo du cloisonnement).
### Sécurité
- Tests : 17/17 backend + parcours frontend validés (itération 5).

## [1.1.0] — 2026-06 — Notifications & Intégrations
### Ajouté
- Canaux SMTP / Discord / Telegram configurables dans l'UI (admin), secrets chiffrés (Fernet) et masqués en lecture, test d'envoi par canal, activation/désactivation.
- Envoi automatique sur alerte critique (`POST /alerts` + BackgroundTasks).
- Tests : 20/20 backend + 14/14 frontend.

## [1.0.0] — 2026-06 — MVP initial
### Ajouté
- Auth JWT + RBAC (admin/technicien/client/lecture seule/invité) + 2FA TOTP.
- Multi-sites, gestion caméras (RTSP/ONVIF config, test, snapshot, PTZ — simulés).
- Mur vidéo (1→64), dashboard (KPI + graphiques), ANPR (recherche, watchlist, export CSV, analyse IA d'image), recherche véhicule, alertes, carte OSM, audit, gestion utilisateurs, paramètres.
- Bilingue FR/EN, thèmes clair/sombre.
- Tests : 30/30 backend + parcours frontend.
