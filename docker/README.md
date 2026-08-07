# MG-VMS · Guide d'installation Docker · v1.0

Installation d'une instance MG-VMS **production ready** sur un serveur
Debian / Ubuntu (nu ou virtualisé) en **3 commandes** depuis un clone Git
vierge.

---

## 🎯 Prérequis serveur

| Élément | Version minimale | Note |
|---|---|---|
| OS | Debian 12 / Ubuntu 22.04+ | ARM non supporté (base `nvidia/cuda`) |
| Docker Engine | 24.x+ | `curl -fsSL https://get.docker.com \| sh` |
| Compose | v2 (plugin) | inclus dans Docker Engine récent |
| GPU (optionnel) | NVIDIA RTX + drivers + `nvidia-container-toolkit` | Sans GPU → voir §CPU-only |
| RAM | 8 Go min (16 Go recommandé) | |
| Disque système | 30 Go | |
| Disque `/mnt/storage` | 500 Go+ selon rétention vidéo | monté séparément |

---

## ⚡ Installation express (3 commandes)

```bash
# 1. Cloner le dépôt
git clone <URL_DEPOT> mg-vms && cd mg-vms

# 2. Préparer volumes hôte et fichier .env
sudo mkdir -p /mnt/storage/{mongodb,video-datastore,models,crops,logs,certs,backups}
sudo chown -R "$USER":"$USER" /mnt/storage
cp docker/.env.example docker/.env

# 3. Build + up
cd docker
docker compose build
docker compose up -d
```

L'application est accessible sur **`https://<IP_SERVEUR>`** (certificat
self-signed généré au premier boot — le navigateur affichera un
avertissement de sécurité tant que tu n'installes pas le certificat sur
tes postes clients ou tant que tu ne fournis pas ton propre certificat).

Voir §HTTPS pour remplacer par ton propre certificat.

---

## 🔧 Configuration `.env`

Toutes les valeurs sont documentées dans `docker/.env.example`.
Les plus critiques :

| Variable | Défaut | Description |
|---|---|---|
| `MGVMS_HOSTNAME` | `mg-vms.local` | CN utilisé dans le cert auto-signé + SubjectAltName |
| `HTTPS_FORCE` | `false` | Si `true`, redirige tout HTTP → HTTPS |
| `MONGO_PATH` | `/mnt/storage/mongodb` | Chemin hôte des données Mongo |
| `VIDEO_DATASTORE` | `/mnt/storage/video-datastore` | Enregistrements + clips + snapshots |
| `CERT_PATH` | `/mnt/storage/certs` | Certificats TLS (auto ou custom) |
| `PIPELINE_TARGET_LATENCY_MS` | `200` | Budget latence pipeline complet |

---

## 🔒 HTTPS — 3 modes possibles

### Mode 1 · Auto self-signed (défaut)
Ne rien faire. Au premier boot, `docker-entrypoint.sh` génère automatiquement :
- `/mnt/storage/certs/fullchain.pem` (valide 10 ans · CN = `MGVMS_HOSTNAME`)
- `/mnt/storage/certs/privkey.pem`

### Mode 2 · Fournir son propre certificat
Copier son couple de fichiers à la place puis redémarrer :
```bash
sudo cp mon.crt /mnt/storage/certs/fullchain.pem
sudo cp mon.key /mnt/storage/certs/privkey.pem
sudo chmod 644 /mnt/storage/certs/fullchain.pem
sudo chmod 600 /mnt/storage/certs/privkey.pem
docker compose restart frontend
```

### Mode 3 · Regénérer un self-signed
```bash
sudo rm -f /mnt/storage/certs/{fullchain,privkey}.pem
docker compose restart frontend
```

---

## 💻 Serveur CPU-only (sans GPU NVIDIA)

Éditer `docker/docker-compose.yml` et **commenter le bloc** `deploy.resources.reservations.devices` du service `backend`. Le pipeline
YOLO fonctionnera alors en CPU (latence plus élevée mais fonctionnel).

Alternative : créer un `docker-compose.override.yml` :
```yaml
services:
  backend:
    deploy:
      resources: {}
```

---

## 🧾 Yarn `--frozen-lockfile`

Actuellement le Dockerfile frontend utilise `yarn install` **sans**
`--frozen-lockfile`. Raison : le monorepo contient encore quelques
résolutions non parfaitement stabilisées (warnings `Resolution field ...`).
Le build est reproductible mais moins strict.

Pour durcir (v1.1) :
1. Vérifier localement : `cd frontend && yarn install --frozen-lockfile`
2. S'assurer que `yarn check --integrity` renvoie `Folder in sync.`
3. Restaurer `--frozen-lockfile` dans `frontend/Dockerfile`.

---

## 🩺 Vérification post-boot

```bash
# Tous les services doivent être "healthy"
docker compose ps

# Backend
curl -sk http://localhost:8001/health
# → {"status":"ok"}

# Frontend HTTPS (self-signed → -k pour ignorer le warning)
curl -skI https://localhost | head -3
# → HTTP/2 200

# MongoDB
docker compose exec mongo mongosh --quiet --eval 'db.runCommand({ping:1})'
# → { ok: 1 }
```

---

## 🔁 Mise à jour

```bash
cd mg-vms
git pull
cd docker
docker compose build --pull
docker compose up -d
```

Le code est **embarqué dans les images** — aucune surprise entre le code
Git et le code exécuté.

---

## 🧯 Logs & Debug

```bash
docker compose logs -f backend         # logs pipeline IA en direct
docker compose logs -f frontend        # logs Nginx / entrypoint TLS
docker compose logs --tail=100 mongo   # 100 dernières lignes Mongo
docker compose exec backend bash       # shell dans le container backend
```

---

## 🚫 Ne PAS faire en production

- ❌ Bind mounter le code (`../backend:/app`, `../frontend:/app`) — cassé
  le principe de builds reproductibles. Ces bind mounts sont réservés au
  fichier `docker-compose.dev.yml` (mode dev uniquement, non fourni ici).
- ❌ Stocker des médias dans MongoDB — tout part sur
  `/mnt/storage/video-datastore/`.
- ❌ Commit un `.env` avec des secrets — utiliser `.env.example` comme
  template.
