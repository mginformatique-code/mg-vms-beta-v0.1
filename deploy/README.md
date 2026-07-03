# MG-VMS — Stack de production (micro-services)

> ⚠️ **Important** : ce dossier contient l'architecture **cible de production**
> (serveur Docker/Kubernetes, GPU pour l'IA, accès réseau caméras).
> Elle n'est **pas exécutée dans l'environnement de développement** (sandbox mono-conteneur).
>
> 👉 Pour un **test Docker immédiat** de l'application de démo (FastAPI + React + MongoDB,
> identique au sandbox), utilisez plutôt **`../deploy-app/`** :
> `cd deploy-app && cp .env.example .env && docker compose up -d --build` → http://localhost:3000

## Démarrage rapide

```bash
cp .env.example .env        # puis modifier TOUTES les valeurs "change_me"
docker compose up -d --build
```

- Frontend : `https://<DOMAIN>` (Vue 3 + Vite + TypeScript, servi par Nginx)
- API + docs : `https://<DOMAIN>/api/docs`
- Compte admin initial : `ADMIN_EMAIL` / `ADMIN_PASSWORD` du `.env` (semé automatiquement)
- Les migrations **Alembic s'exécutent automatiquement** au démarrage de l'API (`entrypoint.sh`).

### Prérequis
| Outil | Version minimale |
|---|---|
| Docker Engine | 24+ |
| Docker Compose | v2 (plugin `docker compose`) |
| GPU NVIDIA (optionnel, IA) | driver 535+ & `nvidia-container-toolkit` |

**Windows** : utiliser Docker Desktop + WSL2. Cloner le dépôt **dans le système de fichiers WSL**
(`~/mg-vms`, pas `C:\...`) pour éviter les problèmes de chemins et de performance.
**Linux** : fonctionne nativement. Pour l'ICMP du `network-monitor`, les capacités
`NET_RAW`/`NET_ADMIN` sont déjà déclarées dans le compose.

## Contenu

```
deploy/
├── docker-compose.yml          # Stack complète (17 services)
├── .env.example                # Variables d'environnement (copier en .env)
├── api/                        # ⭐ API FastAPI (backend principal)
│   ├── app/
│   │   ├── main.py             # Point d'entrée + WebSocket + seed admin
│   │   ├── models.py           # Modèles SQLAlchemy 2.0 (source de vérité du schéma)
│   │   ├── schemas.py          # Schémas Pydantic v2
│   │   ├── ws.py               # Diffusion temps réel (Redis pub/sub multi-instances)
│   │   ├── core/               # config (pydantic-settings), sécurité (JWT/bcrypt), logs JSON
│   │   ├── db/session.py       # Moteur async (psycopg3)
│   │   ├── api/deps.py         # get_current_user, require_role, require_permission, audit
│   │   ├── api/v1/             # 17 modules : auth, users, sites, cameras, streams,
│   │   │                       #   recordings, playback, events, ai, notifications,
│   │   │                       #   maps, storage, monitoring, audit, settings, health
│   │   └── tasks/              # Celery : rétention, usage stockage, notifications
│   ├── alembic/                # Migrations (exécutées au boot)
│   ├── requirements.txt        # Versions verrouillées et testées ensemble
│   └── entrypoint.sh           # alembic upgrade head && uvicorn
├── frontend/                   # ⭐ Vue 3 + Vite + TypeScript + Pinia
│   ├── src/views/              # Login, Dashboard, Caméras, Direct, Enregistrements,
│   │                           #   Événements, Utilisateurs (matrice permissions), Paramètres
│   ├── src/stores/auth.ts      # Session + helper can(permission)
│   └── Dockerfile              # Build multi-étapes Node 20 → Nginx
├── notification/               # ⭐ Service notifications (file Redis → Email/Discord/Telegram/Webhook)
├── ai-engine/                  # YOLOv11 + ByteTrack (CUDA/GPU) + LAPI (fast-alpr)
├── ffmpeg/                     # Ingestion RTSP/ONVIF + go2rtc (WebRTC/HLS)
├── recording/                  # Segments MP4 → MinIO/S3 + timeline + rétention
├── network-monitor/            # Supervision ICMP/SNMP des équipements
├── backup/                     # Sauvegardes planifiées (DB + médias → S3)
├── monitoring/                 # Prometheus, Grafana, Loki, Alertmanager
└── k8s/manifests.yaml          # Variante Kubernetes (Deployments, HPA, Ingress)
```

## Choix techniques (et pourquoi)

| Choix | Raison |
|---|---|
| `psycopg3` (binaire) | Un seul driver sync **et** async, pas de compilation (adieu les erreurs de build) |
| Versions **verrouillées** dans requirements.txt | Ensemble testé : plus de conflits pip aléatoires |
| `bcrypt` natif (sans passlib) | passlib est incompatible avec bcrypt ≥ 4.1 ; l'API native est stable |
| Migrations au démarrage (`entrypoint.sh`) | Une seule source de vérité (`app/models.py` + Alembic), pas de schema.sql divergent |
| JWT httpOnly cookies + refresh | Protection XSS, renouvellement transparent côté frontend |
| Redis pub/sub pour le WebSocket | Fonctionne avec plusieurs réplicas d'API derrière Traefik |
| Vue build multi-étapes | Image finale ~50 Mo (Nginx), Node absent en production |

## Services (docker-compose)

| Service | Rôle |
|---|---|
| reverse-proxy (Traefik) | TLS/Let's Encrypt, routage |
| frontend | UI Vue 3 (Nginx) |
| app-api | API FastAPI + WebSocket (migrations auto au boot) |
| worker / scheduler | Tâches asynchrones (Celery + Redis) : rétention, stockage |
| postgres 16 | Base métier |
| redis 7 | Cache, files Celery, pub/sub WebSocket |
| minio | Stockage objets (enregistrements, exports) |
| ffmpeg-service | Ingestion/transcodage flux caméras (go2rtc : WebRTC/HLS) |
| recording-service | Enregistrement & archivage |
| ai-engine | Détection YOLOv11 + ByteTrack + LAPI (GPU) |
| notification-service | Email / Discord / Telegram / Webhook |
| backup-service | Sauvegardes planifiées |
| prometheus / grafana / loki / alertmanager | Monitoring & logs |

## Permissions granulaires

Chaque utilisateur non-admin porte un dictionnaire `permissions` (JSONB) :
`view_live`, `view_recordings`, `read_anpr`, `stream_hd`, `ptz_control`, `export_files`.
Appliquées **côté API** (dépendance `require_permission`) et **côté UI** (helper `can()` du store Pinia).
Un utilisateur sans `stream_hd` reçoit automatiquement le profil **sub (SD)** sur `/api/streams/{id}/play`.

## Vérifications effectuées

- ✅ `pip install` des requirements API dans un venv propre (Python 3.11) : aucune incompatibilité
- ✅ Import complet de l'application (50 routes), Celery beat, chaîne de migrations Alembic
- ✅ `yarn build` + `vue-tsc --noEmit` du frontend : 0 erreur TypeScript
- ✅ Aucune dépendance nécessitant une compilation locale (wheels binaires uniquement)
