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
