# MG-VMS — Artefacts de déploiement (PRODUCTION)

> ⚠️ **Important** : ce dossier contient des **artefacts d'architecture cible** destinés à un
> environnement de production (serveur Docker/Kubernetes, GPU pour l'IA, accès réseau caméras).
> **Ils ne sont PAS exécutés ni testés dans l'environnement de développement actuel**
> (sandbox mono-conteneur, sans Docker/PostgreSQL/GPU). Le backend de dev tourne sur
> **FastAPI + MongoDB**. La migration vers PostgreSQL se fait via `db/` (schema + SQLAlchemy + Alembic).

## Contenu
```
deploy/
├── docker-compose.yml          # Stack micro-services complète
├── .env.example                # Variables d'environnement
├── api/Dockerfile              # Backend FastAPI (+ workers Celery via la même image)
├── frontend/Dockerfile         # Build React servi par Nginx (+ nginx.conf)
├── ai-engine/Dockerfile        # YOLOv11 + ByteTrack (CUDA/GPU)
├── ffmpeg/Dockerfile           # Ingestion RTSP/ONVIF + transcodage WebRTC/HLS
├── recording/Dockerfile        # Enregistrement, rotation, quota, archivage
├── notification/Dockerfile     # Relais Email/Discord/Telegram/Webhook/MQTT/SMS/Push
├── backup/Dockerfile + backup.sh   # Sauvegarde/restauration (DB + médias -> S3/MinIO)
├── db/
│   ├── schema.sql              # Schéma PostgreSQL optimisé (index GIN trigram, partitions)
│   ├── models.py               # Modèles SQLAlchemy 2.x
│   └── alembic/                # Migrations (env.py + versions/0001_initial.py)
├── monitoring/                 # prometheus.yml, grafana, loki, alertmanager
└── k8s/manifests.yaml          # Namespace, Deployments, StatefulSet PG, Ingress, HPA
```

## Services (docker-compose)
| Service | Rôle |
|---|---|
| reverse-proxy (Traefik) | TLS/Let's Encrypt, routage |
| frontend | UI React (Nginx) |
| app-api | API FastAPI + WebSocket |
| worker / scheduler | Tâches asynchrones (Celery + Redis) |
| postgres | Base métier |
| redis | Cache, files, pub/sub WebSocket multi-instances |
| minio | Stockage objets (enregistrements, exports) |
| ffmpeg-service | Ingestion/transcodage flux caméras |
| recording-service | Enregistrement & archivage |
| ai-engine | Détection YOLOv11 + tracking (GPU) |
| notification-service | Notifications multi-canal |
| backup-service | Sauvegardes planifiées |
| prometheus / grafana / loki / alertmanager | Monitoring & logs |

## Démarrage (sur un serveur de production)
```bash
cp .env.example .env        # puis éditer les secrets
docker compose up -d
# Migrations base :
docker compose exec app-api alembic -c db/alembic.ini upgrade head
```

## Kubernetes
```bash
kubectl apply -f k8s/manifests.yaml
```
Prérequis : ingress-nginx, cert-manager, StorageClass, et NVIDIA device plugin (pour `ai-engine`).

## Notes d'industrialisation
- **Scalabilité** : `app-api` est stateless → HPA (3→12 répliques). Le WebSocket nécessite Redis Pub/Sub pour le fan-out multi-instances.
- **ANPR/Events** : tables partitionnées par mois (`pg_partman`) + index GIN trigram pour la recherche de plaque.
- **Sécurité** : secrets via Vault/KMS, rotation `JWT_SECRET`, TLS bout-en-bout, NetworkPolicies.
- **Sauvegarde** : `backup-service` quotidien vers MinIO/S3 ; tester régulièrement la restauration.
