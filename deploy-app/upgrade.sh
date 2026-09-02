#!/usr/bin/env bash
# ==============================================================================
# MG-VMS · upgrade.sh · v1.0
# ==============================================================================
# Met à jour une installation MG-VMS EXISTANTE vers la dernière version du
# code (nouveau commit sur la branche courante), rebuild + redémarre les
# conteneurs — sans jamais toucher aux données déjà en place.
#
#   cd deploy-app && sudo ./upgrade.sh
#
# Contrat explicite (voir wiki "Installation vs mise à jour") :
#   - Ne modifie JAMAIS le volume MongoDB (pas de dropDatabase, pas de
#     `docker compose down -v`, pas de `docker system prune --volumes`).
#     Utilisateurs, mots de passe, MFA, permissions, caméras, événements,
#     plaques, alertes, réglages : intouchés.
#   - Ne supprime AUCUN fichier d'enregistrement vidéo.
#   - Ne modifie JAMAIS go2rtc.yaml. Ne touche à AUCUN réglage applicatif
#     existant dans .env — seule exception, une ligne ajoutée/mise à jour
#     une fois (UPGRADE_BACKUP_PATH, voir étape 1 ci-dessous).
#   - Aucun menu de purge (paliers A/B/C) — ça n'existe volontairement pas
#     ici. Pour repartir propre ou tout réinitialiser : `install.sh`.
#   - Le seul choix de disque possible ici concerne la SAUVEGARDE de
#     précaution (étape 1) — un scan des disques montés recommande le plus
#     d'espace libre, demandé une seule fois puis mémorisé dans .env
#     (UPGRADE_BACKUP_PATH). Rien à voir avec les chemins Mongo/
#     enregistrements, qui restent le rôle exclusif d'install.sh, ni avec
#     la configuration système (timer reboot, chrony NTP) — étapes de
#     première installation, pas de mise à jour de version. Si l'une
#     d'elles manque sur ce serveur, relancer install.sh une fois suffit
#     (idempotent, aucune donnée
#     touchée non plus).
#
# Ce que fait upgrade.sh, dans l'ordre :
#   1. Sauvegarde MongoDB (mongodump) avant toute chose — disque choisi une
#      fois via scan local, mémorisé ensuite       [--no-backup]
#   2. git fetch + merge --ff-only (échoue fort si divergence, jamais de
#      résolution automatique — jamais de force/reset)        [--no-pull]
#   3. Validation des fichiers de build (mêmes contrôles qu'install.sh)
#   4. docker compose build → up -d (pas de down, pas de prune)
#   5. Attente des healthchecks + rapport de version avant/après
#
# Options :
#   --no-pull      ne pas tirer le dernier commit GitHub (rebuild sur place)
#   --no-backup    ne pas faire de mongodump avant la mise à jour
#   --no-cache     build avec --no-cache
# ==============================================================================
set -euo pipefail

# ─── Couleurs / helpers (identiques à install.sh) ─────────────────────
ROUGE='\033[0;31m'; VERT='\033[0;32m'; JAUNE='\033[1;33m'; BLEU='\033[0;34m'; NC='\033[0m'
echo -e "${BLEU}╔════════════════════════════════════════╗"
echo -e "║                                        ║"
echo -e "║              M G - V M S               ║"
echo -e "║     Vidéosurveillance intelligente     ║"
echo -e "║                                        ║"
echo -e "╚════════════════════════════════════════╝${NC}"
echo
ok()   { echo -e "${VERT}  ✔${NC} $*"; }
warn() { echo -e "${JAUNE}  ⚠${NC} $*"; }
err()  { echo -e "${ROUGE}  ✘ $*${NC}"; }
titre(){ echo -e "\n${BLEU}━━━ $* ━━━${NC}"; }
ERREURS=0
ko()   { err "$*"; ERREURS=$((ERREURS+1)); }

NO_PULL=0; NO_BACKUP=0; NO_CACHE=""
for arg in "$@"; do
  case "$arg" in
    --no-pull)    NO_PULL=1 ;;
    --no-backup)  NO_BACKUP=1 ;;
    --no-cache)   NO_CACHE="--no-cache" ;;
    *) err "Option inconnue : $arg (upgrade.sh n'a pas de menu de purge — voir install.sh)"; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
cd "$SCRIPT_DIR"
echo -e "${BLEU}MG-VMS · Mise à jour v1.0${NC} — repo : $REPO"

# ══════════════════════════════════════════════════════════════════════
# 0. Pré-vérifications — refuse de tourner sur ce qui n'est pas une
#    installation existante (c'est le rôle d'install.sh, pas le nôtre).
# ══════════════════════════════════════════════════════════════════════
titre "0/5 · Pré-vérifications"
if [ ! -f .env ]; then
  err "Aucun .env trouvé dans $SCRIPT_DIR — ce n'est pas une installation existante."
  err "  → Première installation : sudo ./install.sh"
  exit 1
fi
ok ".env existant détecté — installation reconnue"
if [ -z "$(docker compose ps -q 2>/dev/null)" ]; then
  warn "Aucun conteneur MG-VMS en cours — upgrade.sh va quand même builder/démarrer, "
  warn "  mais si c'est une première installation, préférez install.sh (dossiers, "
  warn "  timer reboot, serveur NTP caméras : aucune de ces étapes n'est faite ici)."
fi

# ══════════════════════════════════════════════════════════════════════
# 1. Sauvegarde MongoDB avant toute chose
# ══════════════════════════════════════════════════════════════════════
titre "1/5 · Sauvegarde MongoDB"
if [ "$NO_BACKUP" = 1 ]; then
  warn "--no-backup : sauvegarde ignorée (les données ne sont de toute façon jamais"
  warn "  touchées par ce script — le backup est une précaution supplémentaire, pas"
  warn "  une nécessité pour la mise à jour elle-même)"
elif [ -z "$(docker compose ps -q mongo 2>/dev/null)" ]; then
  warn "Conteneur mongo non démarré — sauvegarde ignorée (rien à sauvegarder pour l'instant)"
else
  # v3.21 · /mnt/storage (disque système) s'est révélé trop petit pour un
  # mongodump de cette base (>90 Go et en croissance) — testé en prod, échec
  # par manque d'espace. Demandé UNE SEULE FOIS (comme les chemins Mongo/
  # enregistrements d'install.sh) : scan des disques montés, triés par
  # espace libre réel décroissant, recommandation = le plus gros. Réponse
  # mémorisée dans .env (UPGRADE_BACKUP_PATH) — plus jamais redemandé après.
  BACKUP_BASE=$(grep -E '^UPGRADE_BACKUP_PATH=' .env 2>/dev/null | tail -1 | cut -d= -f2- || true)
  if [ -z "$BACKUP_BASE" ]; then
    mapfile -t DISK_LINES < <(df -h --output=target,avail -x tmpfs -x overlay -x devtmpfs -x efivarfs 2>/dev/null \
                                 | tail -n +2 | grep -vE '^/boot' | sort -k2 -h -r)
    RECOMMENDED=""
    if [ "${#DISK_LINES[@]}" -gt 0 ]; then
      RECOMMENDED=$(awk '{print $1}' <<< "${DISK_LINES[0]}")
    fi
    if [ -n "$RECOMMENDED" ] && [ -t 0 ]; then
      echo -e "${BLEU}  Disques disponibles (triés par espace libre) :${NC}"
      for line in "${DISK_LINES[@]}"; do echo "    - $line"; done
      echo -ne "${JAUNE}  Sauvegarde MongoDB — Entrée pour $RECOMMENDED (recommandé, le plus d'espace libre), ou chemin complet : ${NC}"
      read -r BACKUP_CHOICE || BACKUP_CHOICE=""
      BACKUP_BASE="${BACKUP_CHOICE:-$RECOMMENDED}"
    elif [ -n "$RECOMMENDED" ]; then
      BACKUP_BASE="$RECOMMENDED"
      warn "non-interactif : disque de sauvegarde auto-sélectionné (le plus d'espace libre) → $BACKUP_BASE"
    else
      BACKUP_BASE="/mnt/storage"
      warn "scan des disques impossible (df indisponible ?) — repli sur $BACKUP_BASE"
    fi
    if grep -q '^UPGRADE_BACKUP_PATH=' .env 2>/dev/null; then
      sed -i "s#^UPGRADE_BACKUP_PATH=.*#UPGRADE_BACKUP_PATH=$BACKUP_BASE#" .env
    else
      echo "UPGRADE_BACKUP_PATH=$BACKUP_BASE" >> .env
    fi
    ok "disque de sauvegarde : $BACKUP_BASE (mémorisé dans .env, ne sera plus redemandé)"
  fi
  BACKUP_DIR="$BACKUP_BASE/mgvms-backups/upgrade-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP_DIR" 2>/dev/null || true
  if docker compose exec -T mongo mongodump --db mgvms --archive 2>/dev/null > "$BACKUP_DIR/mgvms.archive"; then
    TAILLE=$(du -h "$BACKUP_DIR/mgvms.archive" 2>/dev/null | cut -f1)
    ok "sauvegarde MongoDB : $BACKUP_DIR/mgvms.archive ($TAILLE)"
  else
    rm -f "$BACKUP_DIR/mgvms.archive" 2>/dev/null || true
    warn "sauvegarde MongoDB échouée — mise à jour poursuivie quand même (les données"
    warn "  ne sont jamais modifiées par ce script, backup = confort, pas une garantie)"
  fi
fi

# ══════════════════════════════════════════════════════════════════════
# 2. Dernier build GitHub
# ══════════════════════════════════════════════════════════════════════
titre "2/5 · Mise à jour du dépôt (GitHub)"
AVANT_REV=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo "?")
AVANT_VERSION=$(grep -m1 -oE '\[v[^]]+\]' "$REPO/CHANGELOG.md" 2>/dev/null | tr -d '[]' || echo "?")

if [ "$NO_PULL" = 1 ]; then
  warn "--no-pull : dépôt utilisé tel quel ($(git -C "$REPO" log --oneline -1 2>/dev/null || echo 'pas de git'))"
elif [ ! -d "$REPO/.git" ] || ! git -C "$REPO" remote get-url origin >/dev/null 2>&1; then
  err "Pas de dépôt git / remote GitHub configuré dans $REPO — impossible de mettre à jour."
  exit 1
else
  BRANCHE=$(git -C "$REPO" rev-parse --abbrev-ref HEAD)
  if ! git -C "$REPO" diff --quiet || ! git -C "$REPO" diff --cached --quiet; then
    err "Modifications locales non committées détectées dans $REPO — mise à jour ANNULÉE."
    err "  upgrade.sh ne fait jamais de stash/reset automatique. Committez, ou "
    err "  \`git stash\`, puis relancez."
    exit 1
  fi
  git -C "$REPO" fetch origin
  if git -C "$REPO" merge --ff-only "origin/$BRANCHE" >/dev/null 2>&1; then
    ok "À jour sur origin/$BRANCHE → $(git -C "$REPO" log --oneline -1)"
  else
    err "Fast-forward impossible (le dépôt local a divergé d'origin/$BRANCHE)."
    err "  upgrade.sh ne fait JAMAIS de merge/reset automatique en cas de divergence"
    err "  — ça doit être résolu à la main (ou par Claude, en session dédiée) avant"
    err "  de relancer. Dépôt laissé tel quel, rien n'a été modifié."
    exit 1
  fi
fi

# ══════════════════════════════════════════════════════════════════════
# 3. Validation des fichiers de build (mêmes contrôles qu'install.sh)
# ══════════════════════════════════════════════════════════════════════
titre "3/5 · Validation des fichiers de build"
for f in \
  backend/Dockerfile frontend/Dockerfile .dockerignore \
  deploy-app/docker-compose.yml \
  backend/requirements.txt backend/requirements-dev.txt backend/requirements-ai.txt \
  frontend/package.json frontend/yarn.lock frontend/nginx.conf frontend/docker-entrypoint.sh
do
  [ -f "$REPO/$f" ] && ok "présent : $f" || ko "MANQUANT : $f"
done

if [ "$ERREURS" -gt 0 ]; then
  err "\n$ERREURS erreur(s) de validation — mise à jour ANNULÉE (aucun bypass)."
  err "  Rien n'a été rebuild ni redémarré — la version en cours tourne toujours."
  exit 1
fi
ok "Validation complète : 0 erreur"

# ══════════════════════════════════════════════════════════════════════
# 4. Build & redémarrage — PAS de down, PAS de prune : le strict minimum
#    pour amener les conteneurs au nouveau code, données jamais touchées.
# ══════════════════════════════════════════════════════════════════════
titre "4/5 · docker compose build → up"
cd "$SCRIPT_DIR"
docker compose config --quiet && ok "docker compose config : OK"
docker compose build $NO_CACHE
ok "build terminé"
docker compose up -d
ok "conteneurs mis à jour (recréés uniquement pour les images qui ont changé)"

# ══════════════════════════════════════════════════════════════════════
# 5. Attente des healthchecks
# ══════════════════════════════════════════════════════════════════════
titre "5/5 · Attente des healthchecks (mongo → redis → go2rtc → backend → frontend)"
DELAI=420
DEBUT=$(date +%s)
while :; do
  SAINS=$(docker compose ps --format '{{.Name}} {{.Health}}' 2>/dev/null | grep -c healthy || true)
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

APRES_REV=$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo "?")
APRES_VERSION=$(grep -m1 -oE '\[v[^]]+\]' "$REPO/CHANGELOG.md" 2>/dev/null | tr -d '[]' || echo "?")
if [ "$AVANT_REV" = "$APRES_REV" ]; then
  VERSION_LIGNE="  Version      : $APRES_VERSION ($APRES_REV) — inchangée"
else
  N_COMMITS=$(git -C "$REPO" rev-list --count "${AVANT_REV}..${APRES_REV}" 2>/dev/null || echo "?")
  VERSION_LIGNE="  Version      : $AVANT_VERSION ($AVANT_REV) → $APRES_VERSION ($APRES_REV) — $N_COMMITS nouveau(x) commit(s)"
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
PORT_HTTP=$(grep -E '^FRONTEND_HTTP_PORT=' .env | cut -d= -f2); PORT_HTTP=${PORT_HTTP:-3000}
echo -e "\n${VERT}════════════════════════════════════════════════════${NC}"
echo -e "${VERT}  MG-VMS mis à jour — données intactes ✔${NC}"
echo -e "$VERSION_LIGNE"
echo -e "  Application : http://${IP:-<ip-serveur>}:${PORT_HTTP}"
echo -e "${VERT}════════════════════════════════════════════════════${NC}"
