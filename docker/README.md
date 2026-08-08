# ⚠️ Dossier déprécié — voir `/deploy-app/`

Le stack Docker de production canonique vit désormais dans **`/deploy-app/`** :

- `deploy-app/docker-compose.yml` — stack complet (mongo, go2rtc, backend, frontend)
- `deploy-app/docker-compose.prod.yml` — overlay TLS Let's Encrypt (optionnel)
- `deploy-app/.env.example` — variables à copier en `.env`
- `deploy-app/go2rtc.yaml` — config go2rtc

Installation :

```bash
cd deploy-app
cp .env.example .env          # adapter secrets + IP LAN
sudo mkdir -p /mnt/storage/{mongodb,models,crops,logs,certs,backups} \
              /mnt/storage/video-datastore/recordings
docker compose build --no-cache
docker compose up -d
```

Ce dossier `docker/` est conservé uniquement pour l'historique Git ;
les fichiers `docker-compose.yml` et `go2rtc.yaml` dupliqués ont été
supprimés en v1.0-rc4 pour éliminer toute dérive de configuration.
