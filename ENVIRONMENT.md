# MG-VMS · Environment Variables · v1.0

Toutes les variables configurables sont centralisées dans le fichier
`deploy-app/.env` (copie de `deploy-app/.env.example`). Ce document décrit les
conventions de stockage et le rôle de chaque groupe de variables.

---

## Stockage

Toutes les données persistantes sont sur le disque secondaire :

```
/mnt/storage/
├── mongodb/               ← base MongoDB (index + collections)
├── video-datastore/
│   ├── recordings/        ← flux continus H.264/H.265
│   ├── clips/             ← clips d'événements (30s pré + 60s post)
│   └── snapshots/         ← images fixes JPEG
├── models/                ← poids YOLO, FastALPR, PaddleOCR, EasyOCR
├── crops/                 ← crops plaques + véhicules (JPEG)
├── logs/                  ← rotation journalière (LOG_RETENTION_DAYS)
├── certs/                 ← TLS (fullchain.pem + privkey.pem)
└── backups/               ← dumps automatiques + configs exportées
```

**Aucun média ne doit être stocké dans MongoDB.** Les crops sont écrits
sur disque et référencés par ID dans les documents (P0 v1.1 : migration
des blobs base64 encore présents dans Mongo — voir CHANGELOG.md).

---

## MongoDB

```
MONGO_URL     mongodb://mongo:27017
DB_NAME       mgvms
```

Le backend lit ces deux variables (protégées) — le compose les
alimente automatiquement depuis `MONGO_URI` / `MONGO_DATABASE`.

---

## IA

Les modèles sont montés depuis :
```
/mnt/storage/models
```
Ils ne sont **jamais** inclus dans les images Docker (téléchargement à
la première utilisation + persistance sur volume).

---

## HTTPS

Les certificats sont stockés dans :
```
/mnt/storage/certs
├── fullchain.pem
└── privkey.pem
```

Le bouton *"Activer HTTPS"* dans l'UI :
1. génère un couple cert/key (via `cryptography` côté backend)
2. écrit les fichiers dans `/certificates` (monté depuis `certs/`)
3. recharge le reverse proxy Nginx (`docker compose restart frontend`)
4. vérifie la validité TLS via une requête interne

L'auto-cert au boot (self-signed 10 ans) est produit par
`frontend/docker-entrypoint.sh` — remplaçable à chaud.

---

## GPU

MG-VMS cible NVIDIA (CUDA 12.4). Variables Compose :
```
NVIDIA_VISIBLE_DEVICES=all
NVIDIA_DRIVER_CAPABILITIES=compute,video,utility
```
Pour serveur CPU-only : commenter le bloc `deploy.resources.reservations`
du service `backend` dans `docker-compose.yml`.

---

## Pipeline

Objectif budget :
```
< 200 ms  (frame → OCR)
```
Sur RTX A2000. En CPU-only, ~110 ms observés (goulot YOLO = 94 %).

---

## Production

Règles absolues :
- **Aucun bind mount** du code (`../backend:/app`, `../frontend:/app`)
- Le code est embarqué dans les images
- Seules les données sont montées (`/video-datastore`, `/models`, `/crops`,
  `/logs`, `/certificates`, `/backups`)
- Mise à jour = `git pull && docker compose build && docker compose up -d`

---

## Développement local

Les bind mounts sont réservés à `docker-compose.dev.yml` (non fourni ici).
En production, tout est self-contained.
