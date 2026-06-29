# MG-VMS — Product Requirements Document

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

## Implemented (2026-06)
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
