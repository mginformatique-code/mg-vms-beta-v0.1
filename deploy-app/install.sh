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
#   2. Validation des fichiers de build (Dockerfiles, compose,
#      requirements ×3, yarn.lock synchronisé avec package.json)
#   3. Création des dossiers de stockage /mnt/storage/...
#   4. Copie de .env.example → .env (jamais écrasé s'il existe)
#   5. docker compose config → build → up -d
#   6. Attente des healthchecks (mongo → go2rtc → backend → frontend)
#
# Options :
#   --no-pull      ne pas tirer le dernier commit GitHub
#   --check-only   valider les fichiers puis s'arrêter (aucun docker requis)
#   --no-cache     build avec --no-cache
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

NO_PULL=0; CHECK_ONLY=0; NO_CACHE=""
for arg in "$@"; do
  case "$arg" in
    --no-pull)    NO_PULL=1 ;;
    --check-only) CHECK_ONLY=1 ;;
    --no-cache)   NO_CACHE="--no-cache" ;;
    *) err "Option inconnue : $arg"; exit 2 ;;
  esac
done

# Racine du repo = parent de deploy-app/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
cd "$REPO"
echo -e "${BLEU}MG-VMS · Installation v1.0-rc4.5${NC} — repo : $REPO"

# ══════════════════════════════════════════════════════════════════════
# 1. Dernier build GitHub
# ══════════════════════════════════════════════════════════════════════
titre "1/6 · Mise à jour du dépôt (GitHub)"
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
titre "2/6 · Validation des fichiers de build"

# ── 2a. Présence des fichiers critiques ──
for f in \
  backend/Dockerfile frontend/Dockerfile .dockerignore \
  deploy-app/docker-compose.yml deploy-app/go2rtc.yaml deploy-app/mediamtx.yml deploy-app/.env.example \
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
titre "3/6 · Prérequis Docker"
command -v docker >/dev/null || { err "docker introuvable — installez Docker Engine"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "Docker Compose v2 requis (docker compose version)"; exit 1; }
ok "docker $(docker --version | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1) · $(docker compose version --short 2>/dev/null | head -1)"
if docker info 2>/dev/null | grep -qi nvidia; then
  ok "runtime NVIDIA détecté (GPU actif)"
else
  warn "runtime NVIDIA non détecté — le backend démarrera mais l'IA tournera en CPU"
fi

# ══════════════════════════════════════════════════════════════════════
# 4. Stockage /mnt/storage + .env
# ══════════════════════════════════════════════════════════════════════
titre "4/6 · Stockage & configuration"
for d in \
  /mnt/storage/mongodb \
  /mnt/storage/video-datastore/recordings \
  /mnt/storage/models /mnt/storage/crops \
  /mnt/storage/logs /mnt/storage/certs /mnt/storage/backups
do
  mkdir -p "$d" && ok "dossier : $d"
done

cd "$SCRIPT_DIR"
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
  warn ".env créé depuis .env.example — ADAPTEZ IP LAN + secrets :"
  warn "   nano $SCRIPT_DIR/.env  (CORS_ORIGINS, JWT_SECRET, ADMIN_PASSWORD)"
  warn "   ⚠ v1.0-rc4.5 · NE PAS remplir REACT_APP_BACKEND_URL (URLs relatives"
  warn "     obligatoires en prod — la Garde 1 du Dockerfile la refuse)"
fi

# ══════════════════════════════════════════════════════════════════════
# 5. Build & démarrage
# ══════════════════════════════════════════════════════════════════════
titre "5/6 · docker compose config → build → up"
docker compose config --quiet && ok "docker compose config : OK"
docker compose build $NO_CACHE
ok "build terminé"
docker compose up -d
ok "stack démarrée"

# ══════════════════════════════════════════════════════════════════════
# 6. Attente des healthchecks
# ══════════════════════════════════════════════════════════════════════
titre "6/6 · Attente des healthchecks (mongo → mediamtx → backend → frontend)"
DELAI=420   # 7 min (start_period backend 90 s + téléchargement modèles au 1er boot)
DEBUT=$(date +%s)
while :; do
  SAINS=$(docker compose ps --format '{{.Name}} {{.Health}}' 2>/dev/null | grep -c healthy || true)
  TOTAL=$(docker compose ps --format '{{.Name}}' 2>/dev/null | wc -l)
  ECOULE=$(( $(date +%s) - DEBUT ))
  echo -ne "\r  services healthy : $SAINS/$TOTAL (${ECOULE}s)   "
  [ "$SAINS" -ge 4 ] && { echo; break; }
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

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
PORT_HTTP=$(grep -E '^FRONTEND_HTTP_PORT=' .env | cut -d= -f2); PORT_HTTP=${PORT_HTTP:-3000}
echo -e "\n${VERT}════════════════════════════════════════════════════${NC}"
echo -e "${VERT}  MG-VMS installé et opérationnel ✔${NC}"
echo -e "  Application : http://${IP:-<ip-serveur>}:${PORT_HTTP}"
echo -e "  API         : http://${IP:-<ip-serveur>}:8001/api/"
echo -e "  MediaMTX    : WebRTC http://${IP:-<ip-serveur>}:8889 · RTSP rtsp://${IP:-<ip-serveur>}:8654/camera/<id>"
echo -e "  go2rtc      : http://${IP:-<ip-serveur>}:1984 (legacy — démos uniquement)"
echo -e "  Compte admin : voir ADMIN_EMAIL / ADMIN_PASSWORD dans .env"
echo -e "${VERT}════════════════════════════════════════════════════${NC}"
