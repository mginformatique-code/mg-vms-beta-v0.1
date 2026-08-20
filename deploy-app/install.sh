#!/usr/bin/env bash
# ==============================================================================
# MG-VMS · install.sh · v1.0-rc4.5
# ==============================================================================
# Installation/mise à jour complète en UNE commande depuis la racine du repo :
#
#   cd deploy-app && sudo ./install.sh
#
# Étapes :
#   1. Mise à jour du dépôt (dernier build GitHub, --ff-only)     [--no-pull]
#   2. Validation des fichiers de build (Dockerfiles, compose, go2rtc.yaml,
#      requirements ×3, yarn.lock synchronisé avec package.json)
#   3. Prérequis Docker
#   4. Nettoyage pré-installation (down + 3 paliers de prune)    [--no-cleanup]
#      → palier 1 (simple, scopé MG-VMS) : question, Entrée = oui
#      → palier 2 (important, tout l'hôte) : question, Entrée = non
#      → palier 3 (PRO MAX++, + volumes orphelins) : question, Entrée = non
#      → --big-cleanup saute les 3 questions et applique directement le palier 3
#   5. Création des dossiers de stockage /mnt/storage/... + .env
#   6. docker compose config → build → up -d
#   7. Attente des healthchecks (mongo → go2rtc → backend → frontend)
#   8. Purge des données (optionnelle, interactive)          [--no-cleanup]
#      → palier A : enregistrements aux métadonnées corrompues (Entrée = oui)
#      → palier B : TOUS les enregistrements vidéo (Entrée = non)
#      → palier C : réinitialisation totale de la base (taper RESET)
#
# Le résumé final affiche la montée de version (commit avant → après pull).
#
# Options :
#   --no-pull      ne pas tirer le dernier commit GitHub
#   --check-only   valider les fichiers puis s'arrêter (aucun docker requis)
#   --no-cache     build avec --no-cache
#   --no-cleanup   ne pas faire down + prune avant le build
#   --big-cleanup  nettoyage Docker PRO MAX++ (palier 3 : system+builder -a
#                  --volumes, tout l'hôte, pas juste MG-VMS) sans passer par
#                  les questions interactives — jamais les bind mounts/données
# ==============================================================================
set -euo pipefail

# ─── Couleurs / helpers ────────────────────────────────────────────────
ROUGE='\033[0;31m'; VERT='\033[0;32m'; JAUNE='\033[1;33m'; BLEU='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${VERT}  ✔${NC} $*"; }
warn() { echo -e "${JAUNE}  ⚠${NC} $*"; }
err()  { echo -e "${ROUGE}  ✘ $*${NC}"; }
titre(){ echo -e "\n${BLEU}━━━ $* ━━━${NC}"; }
ERREURS=0
ko()   { err "$*"; ERREURS=$((ERREURS+1)); }

NO_PULL=0; CHECK_ONLY=0; NO_CACHE=""; NO_CLEANUP=0; BIG_CLEANUP=0
for arg in "$@"; do
  case "$arg" in
    --no-pull)     NO_PULL=1 ;;
    --check-only)  CHECK_ONLY=1 ;;
    --no-cache)    NO_CACHE="--no-cache" ;;
    --no-cleanup)  NO_CLEANUP=1 ;;
    --big-cleanup) BIG_CLEANUP=1 ;;
    *) err "Option inconnue : $arg"; exit 2 ;;
  esac
done

# Racine du repo = parent de deploy-app/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
cd "$REPO"
echo -e "${BLEU}MG-VMS · Installation v1.0-rc4.5${NC} — repo : $REPO"

# ─── État avant pull (pour le résumé de montée de version en fin de script) ──
AVANT_REV=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo "?")
AVANT_VERSION=$(grep -m1 -oE '\[v[^]]+\]' "$REPO/CHANGELOG.md" 2>/dev/null | tr -d '[]' || echo "?")

# ══════════════════════════════════════════════════════════════════════
# 1. Dernier build GitHub
# ══════════════════════════════════════════════════════════════════════
titre "1/8 · Mise à jour du dépôt (GitHub)"
if [ "$NO_PULL" = 1 ]; then
  warn "--no-pull : dépôt utilisé tel quel ($(git -C "$REPO" log --oneline -1 2>/dev/null || echo 'pas de git'))"
elif [ -d "$REPO/.git" ] && git -C "$REPO" remote get-url origin >/dev/null 2>&1; then
  BRANCHE=$(git -C "$REPO" rev-parse --abbrev-ref HEAD)
  if ! git -C "$REPO" diff --quiet || ! git -C "$REPO" diff --cached --quiet; then
    warn "Modifications locales détectées — pull ignoré (utilisez git stash si voulu)"
  else
    git -C "$REPO" fetch origin
    if git -C "$REPO" merge --ff-only "origin/$BRANCHE" >/dev/null 2>&1; then
      ok "À jour sur origin/$BRANCHE → $(git -C "$REPO" log --oneline -1)"
    else
      warn "Fast-forward impossible (divergence) — dépôt laissé tel quel"
    fi
  fi
else
  warn "Pas de remote GitHub configuré — dépôt utilisé tel quel"
fi

# ══════════════════════════════════════════════════════════════════════
# 2. Validation des fichiers de build
# ══════════════════════════════════════════════════════════════════════
titre "2/8 · Validation des fichiers de build"

# ── 2a. Présence des fichiers critiques ──
for f in \
  backend/Dockerfile frontend/Dockerfile .dockerignore \
  deploy-app/docker-compose.yml deploy-app/go2rtc.yaml deploy-app/.env.example \
  backend/requirements.txt backend/requirements-dev.txt backend/requirements-ai.txt \
  frontend/package.json frontend/yarn.lock frontend/nginx.conf frontend/docker-entrypoint.sh
do
  [ -f "$REPO/$f" ] && ok "présent : $f" || ko "MANQUANT : $f"
done
[ -d "$REPO/data/plugins" ] && ok "présent : data/plugins/ ($(ls "$REPO/data/plugins" | wc -l) plugins)" \
                            || ko "MANQUANT : data/plugins/"
[ -d "$REPO/media" ] && ok "présent : media/ (vidéos démo)" || warn "media/ absent (caméras démo KO)"

# ── 2b. Cohérence backend/Dockerfile (contexte racine) ──
grep -q "COPY backend/requirements.txt" "$REPO/backend/Dockerfile" \
  && ok "backend/Dockerfile : COPY backend/requirements.txt (contexte racine)" \
  || ko "backend/Dockerfile : COPY requirements.txt incompatible avec context: .."
grep -q "COPY data/plugins/" "$REPO/backend/Dockerfile" \
  && ok "backend/Dockerfile : plugins embarqués" \
  || ko "backend/Dockerfile : COPY data/plugins/ manquant"

# ── 2c. Cohérence frontend/Dockerfile ──
grep -q -- "--frozen-lockfile" "$REPO/frontend/Dockerfile" \
  && ok "frontend/Dockerfile : --frozen-lockfile actif" \
  || ko "frontend/Dockerfile : --frozen-lockfile absent (build non reproductible)"
grep -q -- "--production=false" "$REPO/frontend/Dockerfile" \
  && ok "frontend/Dockerfile : devDependencies garanties (--production=false)" \
  || ko "frontend/Dockerfile : --production=false absent (risque craco not found)"
grep -q "^ENV NODE_ENV=development" "$REPO/frontend/Dockerfile" \
  && ko "frontend/Dockerfile : NODE_ENV=development casse yarn build (visual-edits)" \
  || ok "frontend/Dockerfile : NODE_ENV non forcé"

# ── 2d. requirements ×3 : toutes les lignes épinglées ──
for req in requirements.txt requirements-dev.txt requirements-ai.txt; do
  NON_PINNE=$(grep -vE '^\s*(#|$)' "$REPO/backend/$req" | grep -vE '==|@ https?://|--' | head -5 || true)
  if [ -z "$NON_PINNE" ]; then
    ok "backend/$req : 100 % épinglé ($(grep -cE '^\s*[^#\s]' "$REPO/backend/$req") lignes)"
  else
    ko "backend/$req : lignes NON épinglées : $(echo "$NON_PINNE" | tr '\n' ' ')"
  fi
done

# ── 2e. yarn.lock synchronisé avec package.json ──
DESYNC=$(awk '
  /"(dependencies|devDependencies)"[[:space:]]*:/ {actif=1; next}
  actif && /^[[:space:]]*}/ {actif=0}
  actif && /^[[:space:]]*"/ {
    ligne=$0
    gsub(/^[[:space:]]*"/,"",ligne); gsub(/",?[[:space:]]*$/,"",ligne)
    pos=index(ligne,"\": \"")
    if (pos>0) print substr(ligne,1,pos-1) "@" substr(ligne,pos+4)
  }' "$REPO/frontend/package.json" | while read -r dep; do
    grep -qF "$dep" "$REPO/frontend/yarn.lock" || echo "$dep"
  done)
if [ -z "$DESYNC" ]; then
  ok "yarn.lock : synchronisé avec package.json (toutes les dépendances résolues)"
else
  ko "yarn.lock DÉSYNCHRONISÉ — entrées manquantes : $(echo "$DESYNC" | tr '\n' ' ')"
  err "  → régénérer avec Yarn 1.22 : cd frontend && yarn install puis committer yarn.lock"
fi

# ── Bilan validation ──
if [ "$ERREURS" -gt 0 ]; then
  err "\n$ERREURS erreur(s) de validation — installation ANNULÉE (aucun bypass)."
  exit 1
fi
ok "Validation complète : 0 erreur"

# v1.0-rc4 · Vérification non-bloquante de la config Smart Search (LLM)
# Absente = fonctionnalité IA désactivée mais reste du produit intact.
if [ -f .env ] && grep -qE "^EMERGENT_LLM_KEY=.+$" .env; then
  ok "Smart Search IA : EMERGENT_LLM_KEY configurée (recherche IA active)"
else
  warn "Smart Search IA : EMERGENT_LLM_KEY absente dans deploy-app/.env — "
  warn "  la recherche IA renverra 503 (Events restent fonctionnels sans IA)"
  warn "  Obtenez la clé via Emergent Profile → Manage plan → Universal Key"
fi

[ "$CHECK_ONLY" = 1 ] && { echo -e "${VERT}--check-only : terminé.${NC}"; exit 0; }

# ══════════════════════════════════════════════════════════════════════
# 3. Prérequis Docker
# ══════════════════════════════════════════════════════════════════════
titre "3/8 · Prérequis Docker"
command -v docker >/dev/null || { err "docker introuvable — installez Docker Engine"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "Docker Compose v2 requis (docker compose version)"; exit 1; }
ok "docker $(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) · $(docker compose version --short 2>/dev/null | head -1)"
if docker info 2>/dev/null | grep -qi nvidia; then
  ok "runtime NVIDIA détecté (GPU actif)"
else
  warn "runtime NVIDIA non détecté — le backend démarrera mais l'IA tournera en CPU"
fi

# ══════════════════════════════════════════════════════════════════════
# 4. Nettoyage pré-installation
# ══════════════════════════════════════════════════════════════════════
# v3.1.4 · Trois paliers, chacun sa question, du plus prudent au plus
# radical — pour ne jamais forcer un choix entre "rien" et "tout supprime".
# Important : ce compose n'utilise QUE des bind mounts host pour les
# données réelles (mongo/enregistrements/modèles/...) — AUCUN palier, même
# --volumes, ne peut donc perdre de données MG-VMS, quoi qu'il arrive.
# Seuls des volumes Docker *nommés* orphelins (reliquats d'anciennes
# configs, comme observé une fois en prod avec un volume mongo abandonné
# après le passage aux bind mounts) peuvent disparaître au palier 3.
titre "4/8 · Nettoyage pré-installation"
cd "$SCRIPT_DIR"
if [ "$NO_CLEANUP" = 1 ]; then
  warn "--no-cleanup : down + prune ignorés"
else
  if [ -n "$(docker compose ps -q 2>/dev/null)" ]; then
    docker compose down --remove-orphans
    ok "conteneurs arrêtés et retirés (down --remove-orphans, données/.env intacts)"
  else
    ok "aucun conteneur MG-VMS en cours — rien à arrêter"
  fi

  # Palier 1 · Simple — scopé MG-VMS (images dangling + cache de build),
  # rapide et sans impact sur d'autres projets Docker de l'hôte. Coché par
  # défaut (Entrée = oui) : c'est le nettoyage qui était déjà automatique
  # avant l'ajout des paliers 2/3.
  FAIRE_P1=1
  if [ "$BIG_CLEANUP" != 1 ] && [ -t 0 ]; then
    echo -ne "${JAUNE}  Palier 1 · Nettoyage simple (images orphelines + cache de build MG-VMS) ? [Y/n] ${NC}"
    read -r REP1 || REP1=""
    case "$REP1" in [nN]|[nN][oO]) FAIRE_P1=0 ;; esac
  fi
  if [ "$FAIRE_P1" = 1 ]; then
    N_DANGLING=$(docker images -f "dangling=true" -q | wc -l | tr -d ' ')
    docker image prune -f >/dev/null
    docker builder prune -f >/dev/null
    ok "palier 1 : $N_DANGLING image(s) dangling + cache de build purgés"
  else
    warn "palier 1 ignoré"
  fi

  # Palier 2 · Important — TOUTES les images Docker inutilisées de l'hôte
  # (pas seulement MG-VMS) + réseaux orphelins. Implique un rebuild complet
  # (sans cache d'images) au prochain build.
  FAIRE_P2=0
  if [ "$BIG_CLEANUP" = 1 ]; then
    FAIRE_P2=1
  elif [ -t 0 ]; then
    echo -ne "${JAUNE}  Palier 2 · Nettoyage important (TOUTES les images Docker inutilisées de l'hôte, pas juste MG-VMS) ? [y/N] ${NC}"
    read -r REP2 || REP2=""
    case "$REP2" in [oOyY]|[oOyY][uUeE][iIsS]) FAIRE_P2=1 ;; esac
  fi

  # Palier 3 · PRO MAX++ — palier 2 + volumes Docker orphelins (--volumes).
  # Table rase totale côté Docker. Uniquement proposé si le palier 2 est
  # accepté (le 3 est un sur-ensemble du 2, pas une alternative séparée).
  FAIRE_P3=0
  if [ "$FAIRE_P2" = 1 ]; then
    if [ "$BIG_CLEANUP" = 1 ]; then
      FAIRE_P3=1
    elif [ -t 0 ]; then
      echo -ne "${JAUNE}  Palier 3 · Nettoyage PRO MAX++ (palier 2 + volumes Docker orphelins — repart totalement à vide) ? [y/N] ${NC}"
      read -r REP3 || REP3=""
      case "$REP3" in [oOyY]|[oOyY][uUeE][iIsS]) FAIRE_P3=1 ;; esac
    fi
  fi

  if [ "$FAIRE_P3" = 1 ]; then
    warn "PRO MAX++ : supprime TOUTES les images/cache/volumes Docker orphelins de l'hôte (pas seulement MG-VMS). Vos données (bind mounts) ne sont jamais concernées."
    docker system prune -af --volumes
    docker builder prune -af
    ok "palier 3 effectué — Docker reparti à vide (images, cache, volumes orphelins)"
  elif [ "$FAIRE_P2" = 1 ]; then
    warn "Nettoyage important : supprime TOUTES les images/cache Docker inutilisés de l'hôte (pas seulement MG-VMS)."
    docker system prune -af
    docker builder prune -af
    ok "palier 2 effectué — Docker reparti à vide côté images/cache (volumes orphelins conservés)"
  fi
fi

# ══════════════════════════════════════════════════════════════════════
# 5. Stockage /mnt/storage + .env
# ══════════════════════════════════════════════════════════════════════
titre "5/8 · Stockage & configuration"
cd "$SCRIPT_DIR"

# v3.1.3 · Choix des disques UNIQUEMENT à la toute première installation
# (.env pas encore créé) et en interactif — une mise à jour garde toujours
# les chemins déjà configurés, comme le reste de .env.
FRESH_INSTALL=0
[ -f .env ] || FRESH_INSTALL=1
MONGO_PATH_CHOSEN=""
RECORDINGS_PATH_CHOSEN=""

if [ "$FRESH_INSTALL" = 1 ] && [ -t 0 ]; then
  echo
  echo -e "${BLEU}  Disques disponibles :${NC}"
  MOUNTS=(); MOUNT_KINDS=()
  if command -v lsblk >/dev/null 2>&1; then
    while IFS= read -r mp rota; do
      [ -z "$mp" ] && continue
      case "$mp" in /boot|/boot/efi) continue ;; esac
      MOUNTS+=("$mp")
      if [ "$rota" = "1" ]; then MOUNT_KINDS+=("HDD"); else MOUNT_KINDS+=("SSD/NVMe"); fi
    done < <(lsblk -rno MOUNTPOINT,ROTA 2>/dev/null | awk '$1!=""')
  fi
  if [ "${#MOUNTS[@]}" -gt 0 ]; then
    for i in "${!MOUNTS[@]}"; do
      AVAIL=$(df -h --output=avail "${MOUNTS[$i]}" 2>/dev/null | tail -1 | tr -d ' ')
      echo "    $((i+1))) ${MOUNTS[$i]}  [${MOUNT_KINDS[$i]}, ${AVAIL:-?} libre]"
    done
  else
    warn "Aucun disque détecté automatiquement (lsblk indisponible/vide) — saisie manuelle des chemins ci-dessous."
  fi

  echo
  echo -ne "${JAUNE}  Base de données MongoDB — idéalement un SSD. Numéro ci-dessus, chemin complet, ou Entrée pour garder /mnt/storage/mongodb : ${NC}"
  read -r MONGO_CHOICE || MONGO_CHOICE=""
  if [[ "$MONGO_CHOICE" =~ ^[0-9]+$ ]] && [ "$MONGO_CHOICE" -ge 1 ] && [ "$MONGO_CHOICE" -le "${#MOUNTS[@]}" ] 2>/dev/null; then
    MONGO_PATH_CHOSEN="${MOUNTS[$((MONGO_CHOICE-1))]%/}/mgvms-mongodb"
  elif [ -n "$MONGO_CHOICE" ]; then
    MONGO_PATH_CHOSEN="$MONGO_CHOICE"
  fi

  echo -ne "${JAUNE}  Enregistrements vidéo — idéalement un HDD (gros volumes). Numéro ci-dessus, chemin complet, ou Entrée pour garder /mnt/storage/video-datastore/recordings : ${NC}"
  read -r REC_CHOICE || REC_CHOICE=""
  if [[ "$REC_CHOICE" =~ ^[0-9]+$ ]] && [ "$REC_CHOICE" -ge 1 ] && [ "$REC_CHOICE" -le "${#MOUNTS[@]}" ] 2>/dev/null; then
    RECORDINGS_PATH_CHOSEN="${MOUNTS[$((REC_CHOICE-1))]%/}/mgvms-recordings"
  elif [ -n "$REC_CHOICE" ]; then
    RECORDINGS_PATH_CHOSEN="$REC_CHOICE"
  fi
fi

if [ -f .env ]; then
  ok ".env existant conservé (jamais écrasé)"
  # v1.0-rc4.5 · Blindage anti-régression Mixed Content : détecter tôt une
  # valeur polluée qui ferait échouer la Garde 1 du Dockerfile frontend.
  if grep -qE '^REACT_APP_BACKEND_URL=(http|https)://' .env; then
    err ""
    err "❌  .env contient une valeur REACT_APP_BACKEND_URL non vide :"
    grep -E '^REACT_APP_BACKEND_URL=' .env | sed 's/^/     /' >&2
    err ""
    err "  v1.0-rc4.5 · Le frontend en production utilise EXCLUSIVEMENT des"
    err "  URLs relatives (/api, /ws) proxifiées par Nginx same-origin. La"
    err "  Garde 1 du Dockerfile refuse toute valeur non-vide pour éviter"
    err "  un blocage Mixed Content côté navigateur."
    err ""
    err "  → Éditer $SCRIPT_DIR/.env"
    err "  → Vider ou supprimer la ligne : REACT_APP_BACKEND_URL="
    err "  → Relancer sudo ./install.sh"
    exit 1
  fi
else
  cp .env.example .env
  if [ -n "$MONGO_PATH_CHOSEN" ]; then
    sed -i "s#^MONGO_DATA_PATH=.*#MONGO_DATA_PATH=$MONGO_PATH_CHOSEN#" .env
    ok "MongoDB → $MONGO_PATH_CHOSEN"
  fi
  if [ -n "$RECORDINGS_PATH_CHOSEN" ]; then
    sed -i "s#^RECORDINGS_PATH=.*#RECORDINGS_PATH=$RECORDINGS_PATH_CHOSEN#" .env
    ok "Enregistrements vidéo → $RECORDINGS_PATH_CHOSEN"
  fi
  warn ".env créé depuis .env.example — ADAPTEZ IP LAN + secrets :"
  warn "   nano $SCRIPT_DIR/.env  (CORS_ORIGINS, JWT_SECRET, ADMIN_PASSWORD)"
  warn "   ⚠ v1.0-rc4.5 · NE PAS remplir REACT_APP_BACKEND_URL (URLs relatives"
  warn "     obligatoires en prod — la Garde 1 du Dockerfile la refuse)"
fi

# v3.1.3 · Les dossiers créés doivent suivre les chemins RÉELLEMENT
# configurés dans .env (choisis ci-dessus ou déjà présents d'une install
# précédente) — avant ce fix, cette boucle créait toujours /mnt/storage/...
# en dur, indépendamment de MONGO_DATA_PATH/RECORDINGS_PATH dans .env.
MONGO_DIR=$(grep -E '^MONGO_DATA_PATH=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
RECORDINGS_DIR=$(grep -E '^RECORDINGS_PATH=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
for d in \
  "${MONGO_DIR:-/mnt/storage/mongodb}" \
  "${RECORDINGS_DIR:-/mnt/storage/video-datastore/recordings}" \
  /mnt/storage/models /mnt/storage/crops \
  /mnt/storage/logs /mnt/storage/certs /mnt/storage/backups
do
  mkdir -p "$d" && ok "dossier : $d"
done

# ══════════════════════════════════════════════════════════════════════
# 6. Build & démarrage
# ══════════════════════════════════════════════════════════════════════
titre "6/8 · docker compose config → build → up"
docker compose config --quiet && ok "docker compose config : OK"
docker compose build $NO_CACHE
ok "build terminé"
docker compose up -d
ok "stack démarrée"

# ══════════════════════════════════════════════════════════════════════
# 7. Attente des healthchecks
# ══════════════════════════════════════════════════════════════════════
titre "7/8 · Attente des healthchecks (mongo → go2rtc → backend → frontend)"
DELAI=420   # 7 min (start_period backend 90 s + téléchargement modèles au 1er boot)
DEBUT=$(date +%s)
while :; do
  SAINS=$(docker compose ps --format '{{.Name}} {{.Health}}' 2>/dev/null | grep -c healthy || true)
  # Compte dynamique (pas de chiffre en dur) : évite la dérive silencieuse déjà
  # observée quand un service change dans docker-compose.yml sans mise à jour ici.
  TOTAL=$(docker compose ps --format '{{.Name}}' 2>/dev/null | wc -l)
  ECOULE=$(( $(date +%s) - DEBUT ))
  echo -ne "\r  services healthy : $SAINS/$TOTAL (${ECOULE}s)   "
  [ "$TOTAL" -gt 0 ] && [ "$SAINS" -ge "$TOTAL" ] && { echo; break; }
  if [ "$ECOULE" -gt "$DELAI" ]; then
    echo; err "Timeout ${DELAI}s — état actuel :"
    docker compose ps
    err "Logs backend : docker compose logs --tail=50 backend"
    exit 1
  fi
  sleep 5
done

if curl -fsS http://127.0.0.1:8001/health >/dev/null; then
  ok "GET /health → 200"
else
  ko "GET /health en échec"; docker compose ps; exit 1
fi

# ══════════════════════════════════════════════════════════════════════
# 8. Purge des données (optionnelle) — nécessite mongo démarré, donc APRÈS
#    le build/up, contrairement au nettoyage Docker de l'étape 4 (qui lui
#    tourne AVANT, sur un système arrêté).
# ══════════════════════════════════════════════════════════════════════
titre "8/8 · Purge des données (optionnelle)"
cd "$SCRIPT_DIR"
mongo_eval() { docker compose exec -T mongo mongosh mgvms --quiet --eval "$1"; }

if [ "$NO_CLEANUP" = 1 ]; then
  warn "--no-cleanup : purge données ignorée"
elif [ ! -t 0 ]; then
  warn "non-interactif : purge données ignorée (relancer en interactif pour y accéder)"
else
  # Palier A · Enregistrements aux métadonnées corrompues — durée aberrante
  # (bug ffprobe/segment corrigé dans recorder.py, voir commentaire dans le
  # code : un flux source avec coupures peut produire un MP4 dont ffprobe
  # rapporte une durée délirante). Ne perd aucune vraie donnée : seuls des
  # index cassés (fichier déjà introuvable ou durée absurde) disparaissent.
  N_CASSES=$(mongo_eval 'db.recordings.countDocuments({duration_sec: {$gt: 600}})' 2>/dev/null || echo "?")
  if [ "$N_CASSES" != "0" ] && [ "$N_CASSES" != "?" ]; then
    echo -ne "${JAUNE}  Palier A · $N_CASSES enregistrement(s) à la durée aberrante détecté(s) (métadonnées corrompues) — les purger ? [Y/n] ${NC}"
    read -r REPA || REPA=""
    case "$REPA" in
      [nN]|[nN][oO]) warn "palier A ignoré" ;;
      *) if mongo_eval 'db.recordings.deleteMany({duration_sec: {$gt: 600}})' >/dev/null 2>&1; then
           ok "palier A : $N_CASSES enregistrement(s) corrompu(s) purgé(s) de l'index"
         else
           ko "palier A : échec de la purge Mongo"
         fi ;;
    esac
  elif [ "$N_CASSES" = "?" ]; then
    warn "palier A : impossible d'interroger mongo — ignoré"
  else
    ok "palier A : aucun enregistrement corrompu détecté"
  fi

  # Palier B · TOUS les enregistrements vidéo — fichiers + index Mongo.
  # Caméras/utilisateurs/config/événements/plaques conservés : repart juste
  # sans historique vidéo (utile pour repartir propre après une migration
  # de disque, un test, ou une corruption étendue).
  echo -ne "${JAUNE}  Palier B · Supprimer TOUS les enregistrements vidéo (fichiers + index — caméras/événements/utilisateurs conservés) ? [y/N] ${NC}"
  read -r REPB || REPB=""
  case "$REPB" in
    [oOyY]|[oOyY][uUeE][iIsS])
      warn "Suppression de tous les enregistrements vidéo..."
      docker compose exec -T backend sh -c 'find /app/recordings -type f -name "*.mp4" -delete' 2>/dev/null || true
      if mongo_eval 'db.recordings.deleteMany({})' >/dev/null 2>&1; then
        ok "palier B : tous les enregistrements vidéo supprimés (fichiers + index)"
      else
        ko "palier B : échec de la purge Mongo (fichiers déjà supprimés)"
      fi
      ;;
    *) ;;
  esac

  # Palier C · Réinitialisation TOTALE de la base — caméras, sites, événements,
  # plaques, enregistrements, utilisateurs additionnels : TOUT disparaît.
  # Le compte admin est recréé automatiquement au redémarrage du backend
  # (backend/seed.py, depuis ADMIN_EMAIL/ADMIN_PASSWORD dans .env) — pas de
  # perte d'accès, mais TOUTE la donnée métier saute. Confirmation par mot
  # de passe (pas un simple y/N) vu la gravité.
  echo -ne "${ROUGE}  Palier C · RÉINITIALISATION TOTALE de la base (caméras/événements/plaques/utilisateurs — TOUT supprime, irréversible) — tapez RESET pour confirmer, n'importe quoi d'autre pour annuler : ${NC}"
  read -r REPC || REPC=""
  if [ "$REPC" = "RESET" ]; then
    warn "Réinitialisation totale de la base MongoDB..."
    docker compose exec -T backend sh -c 'find /app/recordings -type f -name "*.mp4" -delete' 2>/dev/null || true
    if mongo_eval 'db.dropDatabase()' >/dev/null 2>&1; then
      docker compose restart backend >/dev/null 2>&1 || true
      ok "palier C : base réinitialisée — compte admin recréé au redémarrage (ADMIN_EMAIL/ADMIN_PASSWORD dans .env)"
    else
      ko "palier C : échec de la réinitialisation Mongo"
    fi
  else
    ok "palier C ignoré"
  fi
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
PORT_HTTP=$(grep -E '^FRONTEND_HTTP_PORT=' .env | cut -d= -f2); PORT_HTTP=${PORT_HTTP:-3000}

# ─── Montée de version (comparaison avec l'état capturé avant le pull) ──────
APRES_REV=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo "?")
APRES_VERSION=$(grep -m1 -oE '\[v[^]]+\]' "$REPO/CHANGELOG.md" 2>/dev/null | tr -d '[]' || echo "?")
if [ "$AVANT_REV" = "?" ] || [ "$APRES_REV" = "?" ]; then
  VERSION_LIGNE="  Version      : $APRES_VERSION ($APRES_REV)"
elif [ "$AVANT_REV" = "$APRES_REV" ]; then
  VERSION_LIGNE="  Version      : $APRES_VERSION ($APRES_REV) — inchangée"
else
  N_COMMITS=$(git -C "$REPO" rev-list --count "${AVANT_REV}..${APRES_REV}" 2>/dev/null || echo "?")
  VERSION_LIGNE="  Version      : $AVANT_VERSION ($AVANT_REV) → $APRES_VERSION ($APRES_REV) — $N_COMMITS nouveau(x) commit(s)"
fi

echo -e "\n${VERT}════════════════════════════════════════════════════${NC}"
echo -e "${VERT}  MG-VMS installé et opérationnel ✔${NC}"
echo -e "$VERSION_LIGNE"
echo -e "  Application : http://${IP:-<ip-serveur>}:${PORT_HTTP}"
echo -e "  API         : http://${IP:-<ip-serveur>}:8001/api/"
echo -e "  Go2RTC      : http://${IP:-<ip-serveur>}:1984 (interne ; utilisé par le backend uniquement)"
echo -e "  Compte admin : voir ADMIN_EMAIL / ADMIN_PASSWORD dans .env"
echo -e "${VERT}════════════════════════════════════════════════════${NC}"
