# MG-VMS — Test Docker (application réelle)

Ce dossier permet de lancer **l'application MG-VMS complète et fonctionnelle**
(FastAPI + React + MongoDB) en Docker, **identique au sandbox**, en une commande.

> Pour l'architecture micro-services de production (PostgreSQL, GPU YOLOv11, ffmpeg
> RTSP, MinIO, Kubernetes…), voir le dossier `../deploy/`. Celle-ci exige des caméras
> RTSP et des GPU réels et n'est pas destinée à un simple test sur poste.

## Prérequis
- Docker + Docker Compose v2 (`docker compose version`)
- GPU NVIDIA (prod) : driver ≥ 550 + nvidia-container-toolkit
- Points de montage stockage créés AVANT le premier démarrage :
```bash
sudo mkdir -p /mnt/storage/mongodb \
              /mnt/storage/video-datastore/recordings \
              /mnt/storage/models /mnt/storage/crops \
              /mnt/storage/logs /mnt/storage/certs /mnt/storage/backups
```

## Démarrage rapide
```bash
cd deploy-app
cp .env.example .env          # ajustez secrets + IP LAN (obligatoire)
docker compose config --quiet # validation de la configuration
docker compose build --no-cache
docker compose up -d
docker compose ps             # attendre : mongo/go2rtc/backend healthy
curl -fsS http://127.0.0.1:8001/health   # → 200
```

Ordre de démarrage garanti par les healthchecks :
`mongo healthy → go2rtc healthy → backend healthy → frontend`.

Puis ouvrez :
- **Application** : http://localhost:3000
- **API** : http://localhost:8001/api/

Connexion administrateur (créée automatiquement) :
- Email : `admin@mg-vms.com`
- Mot de passe : `Admin@2026`

## Commandes utiles
```bash
docker compose logs -f backend     # logs API
docker compose logs -f frontend    # logs build/Nginx
docker compose ps                  # état des conteneurs
docker compose down                # arrêt
docker compose down -v             # arrêt + suppression des données Mongo
```

## Notes
- Le backend **initialise automatiquement** les données de démonstration au premier
  démarrage (admin, sites, caméras, événements ANPR, équipements réseau, matériel…).
- Les données persistent via bind mounts host (`/mnt/storage/...` — voir `.env`).
  Aucun volume Docker nommé, aucun bind mount de code (images immuables).
- `REACT_APP_BACKEND_URL` est **figé au build** du frontend. Pour déployer derrière un
  domaine, rebuild avec la bonne valeur :
  `REACT_APP_BACKEND_URL=https://api.mondomaine.fr docker compose up -d --build`
  et mettez `CORS_ORIGINS=https://app.mondomaine.fr` côté backend.
- L'IA / ANPR vidéo réel et l'accélération GPU ne font **pas** partie de ce test
  (voir `../deploy/`). Ici l'ANPR fonctionne en mode simulation.

## Dépannage

### Erreur `Cannot find module 'ajv/dist/compile/codegen'` au build frontend
Cette erreur signifie que le build a utilisé **npm** au lieu de **Yarn + yarn.lock**
(conflit ajv v8 / ajv-keywords recalculé par npm). Le Dockerfile actuel du dépôt
utilise `yarn install --frozen-lockfile` : vérifiez que vous buildez bien depuis
une **copie à jour du dépôt** :

```bash
cd /home/docker
rm -rf mg-vms                      # supprimer l'ancienne copie obsolète
git clone https://github.com/<votre-compte>/mg-vms.git
cd mg-vms/deploy-app
cp .env.example .env
docker compose build --no-cache && docker compose up -d
```

⚠️ Attention à ne pas cloner le dépôt *à l'intérieur* d'une ancienne copie puis
builder depuis l'ancienne : `docker compose` utilise les fichiers du dossier courant
(`../frontend`, `../backend` relatifs au compose).

## Vidéo réelle (go2rtc)
Depuis la version « réelle », la vue live n'est plus simulée :
- Le service **go2rtc** ingère les flux **RTSP réels** de vos caméras et les transcode.
- Ajoutez une caméra avec son URL RTSP (ou via **Découverte ONVIF**) : le flux
  apparaît en direct dans « Mur vidéo », le test de connexion utilise **ffprobe**
  (résolution/fps/codec réels), l'instantané est une **vraie frame** du flux.
- Une **caméra de démonstration** (mire H.264 générée localement) valide le
  pipeline sans caméra physique.
- Sur Linux, pour la découverte ONVIF (multicast) et un accès LAN direct,
  décommentez `network_mode: host` sur le service `go2rtc` et mettez
  `GO2RTC_URL=http://localhost:1984` dans `.env`.
