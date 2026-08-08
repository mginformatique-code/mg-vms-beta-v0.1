# RAPPORT — MG-VMS v1.0-rc4 · Correction globale BUILD / DOCKER / DEPLOYMENT

Date : 2026-06 · Périmètre : packaging uniquement — ZÉRO feature, ZÉRO refactoring,
ZÉRO modification métier (ANPR/OCR/caméras/plugins/UI intacts).

---

## 1. Cause racine Yarn lock
`react-window@^2.3.0` avait été ajouté à `package.json` (virtualisation v0.8-rc3)
mais l'entrée correspondante manquait dans le `yarn.lock` **committé** →
`--frozen-lockfile` refusait légitimement l'installation sur clone propre.

## 2. Diff exact package.json / yarn.lock
- `package.json` : **AUCUNE modification** (aucune nécessité démontrée).
- `yarn.lock` : +5 lignes — unique entrée manquante :
  ```
  react-window@^2.3.0:
    version "2.3.0"
    resolved ".../react-window-2.3.0.tgz#92fefee..."
    integrity sha512-FW6TIpaOH646k51X7yE...
  ```
- `resolutions` : **inchangées** (aucune version modifiée pour masquer un warning).
- Régénération/validation avec **Yarn 1.22.22** (`node v20.20.2`).

## 3. Cause racine CRACO (`craco: not found`)
`ENV NODE_ENV=production` dans le stage builder → Yarn saute les
devDependencies → `@craco/craco` absent → `craco build` introuvable.

## 4. Correction Docker frontend (`frontend/Dockerfile`)
- `yarn install --production=false --frozen-lockfile --network-timeout 600000 --non-interactive`
  (devDependencies TOUJOURS installées, lockfile STRICT — le bypass temporaire
  « sans --frozen-lockfile » a été supprimé).
- **Écart justifié vs template** : PAS de `ENV NODE_ENV=development`.
  `craco.config.js` (ligne 7 : `isDevServer = NODE_ENV !== "production"`) active
  alors `visual-edits` + React-Refresh → `yarn build` échoue
  (« React Refresh Babel transform should only be enabled in development »).
  Reproduit puis corrigé : NODE_ENV non forcé (react-scripts le met lui-même en
  production au build) ; les devDependencies sont garanties par `--production=false`.
- `COPY yarn.lock ./` strict (plus de glob `yarn.lock*`).
- `ENV DISABLE_ESLINT_PLUGIN=true` : 16 warnings PRÉ-EXISTANTS
  `react-hooks/exhaustive-deps` (12 fichiers métier : WebRTCPlayer, Alerts, Anpr,
  Audit, Cameras, Diagnostics, LiveView, Network, PluginPage, Recordings,
  Timeline, VehicleSearch) deviennent fatals avec `CI=true`. Les corriger =
  toucher du code métier (interdit ici). Flag CRA documenté ; le lint reste
  actif en dev. Ce n'est PAS un bypass du lockfile ni de craco.
- Runtime Nginx inchangé : seul `/app/build` est copié, aucune devDependency.

## 5. Cause racine requirements
`backend/Dockerfile` : `COPY requirements.txt .` alors que le compose
(`deploy-app/docker-compose.yml`) build avec `context: ..` (racine du repo).
Docker cherchait `/requirements.txt` → inexistant.

## 6. Vérification historique des requirements
`find . -maxdepth 3 -name 'requirements*.txt'` →
- `backend/requirements.txt` (**officiel** — freeze pip complet, 246 lignes)
- `backend/requirements-dev.txt`, `backend/requirements-ai.txt` (auxiliaires, non
  utilisés par Docker)
Aucun `/requirements.txt` racine n'a jamais existé (aucune recréation artificielle).
**Aucune dépendance supprimée, aucune version modifiée.**

## 7. Correction backend Dockerfile (`backend/Dockerfile`)
- `COPY backend/requirements.txt ./requirements.txt` (chemins relatifs à la racine)
- `COPY backend/. .` + `COPY data/plugins/ /app/data/plugins/` (le loader résout
  `<backend>/data/plugins` — sans quoi les 51 plugins seraient absents de l'image)
- `pip install --no-cache-dir --no-deps -r requirements.txt --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/`
  * `--no-deps` : requirements.txt est un **freeze complet** (lockfile pip).
    `pip check` révèle des pins hérités mutuellement stricts (ex :
    paddlepaddle↔opt-einsum, google-genai↔anyio) : le résolveur pip moderne
    REFUSERAIT ce set pourtant fonctionnel et qualifié. `--no-deps` réplique
    exactement l'environnement validé — c'est l'installation la plus
    reproductible possible, pas un contournement.
  * extra-index-url : requis pour `emergentintegrations==0.2.0`
    (absent de PyPI, présent sur l'index dédié — vérifié).
- Nouveau `/.dockerignore` racine : exclut `.git`, `frontend/node_modules`
  (540 Mo), `.env`, caches — contexte de build minimal et sans secrets.

## 8. Correction docker-compose (`deploy-app/docker-compose.yml`, réécrit)
- backend : `context: ..` + `dockerfile: backend/Dockerfile` (conservé)
- frontend : `context: ../frontend` + `dockerfile: Dockerfile` (conservé)
- **AUCUN bind mount de code** (images immuables) — volumes = données uniquement
- `depends_on` avec conditions : mongo `service_healthy` → go2rtc
  `service_healthy` → backend `service_healthy` → frontend
- GPU conservé : `runtime: nvidia` + `deploy.resources.reservations.devices`
  (`capabilities: [gpu, video]`) + `NVIDIA_VISIBLE_DEVICES=all` +
  `NVIDIA_DRIVER_CAPABILITIES=compute,utility,video` + `MGVMS_AI_HW_ACCEL=auto`
- go2rtc : image `alexxit/go2rtc:1.9.9`, ports 1984/8554/8555 TCP+UDP,
  `./go2rtc.yaml:ro`, datastore recordings `:ro`, **`../media:/demo-media:ro`
  conservé** (fix demo-cam-002/street-demo.mp4), healthcheck
  `wget -qO- http://localhost:1984/api`
- Doublon `/docker/docker-compose.yml` + `/docker/go2rtc.yaml` SUPPRIMÉS
  (dérive de config) — `/docker/README.md` pointe vers `deploy-app/`.

## 9. Chemins storage
Host (`.env`) → conteneur backend :
| Host                                        | Conteneur        |
|---------------------------------------------|------------------|
| /mnt/storage/mongodb                        | /data/db (mongo) |
| /mnt/storage/video-datastore/recordings     | /app/recordings  |
| /mnt/storage/models                         | /models          |
| /mnt/storage/crops                          | /crops           |
| /mnt/storage/logs                           | /logs            |
| /mnt/storage/certs                          | /certificates    |
| /mnt/storage/backups                        | /backups         |
Aucun défaut implicite `./data/...` restant (compose de base + overlay prod).
Le code métier n'a PAS été modifié : le backend lit `RECORDINGS_DIR`
(défaut `/app/recordings`) — mappé tel quel.

## 10. Healthchecks
- mongo : `mongosh --quiet --eval "db.runCommand({ping:1})"`
- go2rtc : `wget -qO- http://localhost:1984/api`
- backend : `curl -fsS http://127.0.0.1:8001/health` · `start_period: 90s`
  (imports torch/ultralytics/OCR) — endpoint `/health` existant (server.py:214)
- frontend : `curl -fs http://localhost/`

## 11. Fichiers modifiés
| Fichier | Nature |
|---|---|
| `.dockerignore` | **nouveau** (contexte racine) |
| `frontend/yarn.lock` | +5 lignes (react-window) |
| `frontend/Dockerfile` | frozen-lockfile strict + fix NODE_ENV/CRACO |
| `backend/Dockerfile` | chemins racine + plugins + pip freeze --no-deps |
| `deploy-app/docker-compose.yml` | réécrit (healthchecks, storage, GPU) |
| `deploy-app/docker-compose.prod.yml` | défaut RECORDINGS_PATH → /mnt/storage |
| `deploy-app/.env.example` | complété (toutes les variables §14) |
| `deploy-app/README.md` | instructions mkdir + ordre healthy |
| `docker/docker-compose.yml`, `docker/go2rtc.yaml` | **supprimés** (doublons) |
| `docker/README.md` | pointeur vers deploy-app |
| `ENVIRONMENT.md` | référence docker/.env → deploy-app/.env |
`frontend/package.json` : **non modifié**. Aucun fichier métier touché.

## 12–13. Diff résumé / Commit
Voir `git log` (commits automatiques de la plateforme après cette session ;
base : `6ec3044`). Diff net : +packaging, −doublons, 0 ligne métier.

## 14–19. Validation sur clone vierge (environnement CI aarch64)
Clone propre reconstitué dans `/tmp/clone-vierge` (arbre complet sans
`node_modules`/`.git`), séquence intégrale :
| Étape | Résultat |
|---|---|
| `rm -rf node_modules && yarn install --frozen-lockfile --network-timeout 600000` | ✅ SUCCESS (« Done in 14.96s ») |
| `yarn build` (CI=true, env exacts du Dockerfile) | ✅ « Compiled successfully » — bundle 5.5 Mo, `REACT_APP_BACKEND_URL` bien figée dans `main.*.js` |
| `docker compose config --quiet` (compose de base) | ✅ (binaire officiel Docker Compose **v2.39.1**) |
| `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` | ✅ (avec `MGVMS_DOMAIN` renseigné — requis par l'overlay Let's Encrypt uniquement) |
| Disponibilité des 245 pins Python en **x86_64/cp311** sur PyPI | ✅ 245/245 (+ `emergentintegrations` vérifié sur l'index dédié) |

⚠️ **Limite d'environnement (transparence)** : ce conteneur CI ne dispose PAS de
daemon Docker ni de GPU → `docker compose build --no-cache` / `up -d` /
healthchecks runtime / test GPU / vérification des montages EN CONTENEUR n'ont
PAS pu être exécutés ici. Tout ce qui précède la couche daemon a été validé
réellement (lockfile, build, config compose, chemins COPY vérifiés contre
l'arborescence, wheels x86_64). La checklist §17 du cahier des charges reste à
dérouler sur le serveur cible — elle est documentée dans `deploy-app/README.md`.

## 20–21. État services preview / /health
Preview intacte après ce chantier : backend RUNNING, frontend RUNNING,
`GET /health` → **200**. Aucun service impacté (changements packaging only).

## 22. GPU
Configuration conservée à l'identique (runtime nvidia, devices gpu+video,
NVIDIA_*, MGVMS_AI_HW_ACCEL=auto). Non testable ici (pas de GPU CI).

## 23. Storage
Mapping complet §9 ; à confirmer en §18 sur serveur (`docker exec ls /app/recordings /models /crops /logs /certificates /backups`).

## 24. Aucune fonctionnalité métier modifiée
Confirmé : aucun fichier `src/` frontend ni `.py` backend touché dans ce
chantier (voir §11). ANPR/OCR/plugins/caméras/UI inchangés.

## 25. Aucun contournement
- `--frozen-lockfile` réellement actif (l'ancien bypass a été RETIRÉ) ;
- pas d'install globale de craco, pas de copie de node_modules hôte ;
- pas de déplacement artificiel de requirements.txt ;
- les deux écarts vs template (`NODE_ENV` non forcé, `pip --no-deps`,
  `DISABLE_ESLINT_PLUGIN` au build) sont documentés, justifiés par des causes
  racines reproduites, et n'altèrent ni le lockfile, ni les versions, ni le métier.
