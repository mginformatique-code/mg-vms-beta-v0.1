# MG-VMS — Test Docker (application réelle)

Ce dossier permet de lancer **l'application MG-VMS complète et fonctionnelle**
(FastAPI + React + MongoDB) en Docker, **identique au sandbox**, en une commande.

> Pour l'architecture micro-services de production (PostgreSQL, GPU YOLOv11, ffmpeg
> RTSP, MinIO, Kubernetes…), voir le dossier `../deploy/`. Celle-ci exige des caméras
> RTSP et des GPU réels et n'est pas destinée à un simple test sur poste.

## Prérequis
- Docker + Docker Compose v2 (`docker compose version`)
- ~2 Go RAM libres. Aucun GPU requis.

## Démarrage rapide
```bash
cd deploy-app
cp .env.example .env          # ajustez les secrets si besoin
docker compose up -d --build  # build + lancement (première fois : ~3-5 min)
```

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
- Les données persistent dans le volume `mongo_data`.
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
