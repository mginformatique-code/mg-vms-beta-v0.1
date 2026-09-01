# ==============================================================================
# MG-VMS · Frontend · Production Dockerfile v1.0-rc4.5
# ==============================================================================
# Multi-stage : build React (node:20) puis serve via nginx (alpine).
# L'image contient l'entrypoint auto-cert : au démarrage, si aucun certificat
# TLS n'est présent dans /etc/nginx/certs/ un self-signed est généré.
# L'utilisateur peut swapper à chaud en remplaçant fullchain.pem/privkey.pem.
#
# v1.0-rc4.5 · BLINDAGE URLs RELATIVES (P0 root cause fix) :
# -----------------------------------------------------------------------------
# En PRODUCTION, le frontend DOIT utiliser exclusivement des URLs relatives
# (/api, /ws, /go2rtc, ...). Toutes les requêtes sont proxifiées par Nginx
# same-origin vers le backend, évitant tout Mixed Content HTTPS→HTTP.
#
# REACT_APP_BACKEND_URL est FORCÉE à chaîne vide pendant `yarn build`.
# Toute tentative d'injection d'une URL absolue (http:// ou https://) via
# build args ou variable d'environnement fait ÉCHOUER le build (garde 1).
# Un scan post-build vérifie l'absence d'URL absolue vers /api dans le
# bundle JS généré (garde 2). Aucune régression silencieuse possible.
#
# En DÉVELOPPEMENT (`yarn start`), CRA lit `.env` local et REACT_APP_BACKEND_URL
# peut pointer vers un backend distant (preview.emergentagent.com, etc.).

# ─── Stage 1 : build React ────────────────────────────────────────────
FROM node:20-bookworm-slim AS builder

# NE PAS forcer NODE_ENV ici :
#   - craco.config.js active visual-edits/React-Refresh si NODE_ENV != production
#     (casse `yarn build` avec « React Refresh Babel transform ... »)
#   - `craco build` (react-scripts) force lui-même NODE_ENV=production.
# Les devDependencies (dont @craco/craco) sont garanties par
# `--production=false` ci-dessous, indépendamment de NODE_ENV.
ENV CI=true
ENV GENERATE_SOURCEMAP=false
# 16 warnings pré-existants `react-hooks/exhaustive-deps` (12 fichiers métier)
# deviendraient fatals avec CI=true. Les corriger = toucher du code métier
# (interdit — zéro régression). Le lint reste actif en dev/preview ; on
# désactive uniquement le plugin ESLint pendant le build de production
# (flag CRA documenté, pas un bypass du lockfile ni de craco).
ENV DISABLE_ESLINT_PLUGIN=true

WORKDIR /app

COPY package.json ./
COPY yarn.lock ./

# v1.0-rc4 · Lockfile strict : le build échoue si package.json/yarn.lock
# divergent (reproductibilité garantie — aucun bypass).
RUN yarn install \
      --production=false \
      --frozen-lockfile \
      --network-timeout 600000 \
      --non-interactive

COPY . .

# ─── Garde 1 : REACT_APP_BACKEND_URL doit être vide en production ─────
# Si l'utilisateur tente de passer --build-arg REACT_APP_BACKEND_URL=http://X
# ou définit la variable dans docker-compose args, le build ÉCHOUE avec un
# message explicite. Cela évite tout Mixed Content en prod.
ARG REACT_APP_BACKEND_URL=""
RUN if [ -n "$REACT_APP_BACKEND_URL" ]; then \
      echo ""; \
      echo "==============================================================="; \
      echo "❌  BUILD REFUSÉ — v1.0-rc4.5 · Blindage URLs relatives"; \
      echo "==============================================================="; \
      echo "REACT_APP_BACKEND_URL a été injectée avec :"; \
      echo "    \"$REACT_APP_BACKEND_URL\""; \
      echo ""; \
      echo "En production, le frontend doit utiliser des URLs relatives"; \
      echo "(/api, /ws) proxifiées par Nginx. Injecter une URL absolue"; \
      echo "provoquerait un blocage Mixed Content côté navigateur."; \
      echo ""; \
      echo "→ Retirer REACT_APP_BACKEND_URL de deploy-app/.env"; \
      echo "→ Retirer la section args: REACT_APP_BACKEND_URL du"; \
      echo "  docker-compose.yml (bloc frontend)"; \
      echo "→ Relancer: docker compose build --no-cache frontend"; \
      echo "==============================================================="; \
      exit 1; \
    fi

# Force explicite à vide (au cas où l'env parent aurait déjà exporté la var).
# CRA lira alors "" et le template ${REACT_APP_BACKEND_URL}/api/... produira
# "/api/..." (URL relative) dans le bundle final.
ENV REACT_APP_BACKEND_URL=""

# ─── Identifiant de build (force le relogin après un rebuild) ────────
# v1.0-rc4.6 · Un token JWT valide (jusqu'à 8h/7j) survit à un rebuild —
# après une mise à jour, F5 restaure la session au lieu de forcer un
# nouveau login. Fichier statique horodaté à chaque build, servi tel
# quel par nginx (pas bakée dans le bundle JS, pas de rebuild du bundle
# nécessaire pour que ça change) : le frontend le compare à la valeur
# qu'il a stockée localement au dernier login et purge la session locale
# si elle diffère, avant même de tenter /auth/me.
RUN date +%s%N > public/build_id.txt

RUN yarn build

# ─── Garde 2 : scan post-build du bundle ──────────────────────────────
# Le bundle NE DOIT PAS contenir d'URL absolue vers un endpoint MG-VMS.
# On cible spécifiquement les endpoints MG-VMS connus (/api/auth, /api/cameras,
# /api/system, /api/events, /api/ws) préfixés par un schéma http(s):// qui
# indiquerait REACT_APP_BACKEND_URL bakée. Cela évite les faux positifs sur
# les URLs externes légitimes (discord webhooks, github API dans placeholders,
# etc.).
RUN set -e; \
    PATTERN='(http|https)://[^"'"'"' ]+/api/(auth|cameras|system|events|ws|plates|users|vehicles|recordings|discovery|plugins|stream|mjpeg-direct|smart-search|smart-zones|workflows|audit|alerts|notifications|diagnostics|pipeline|gpu|anpr|rbac|mfa|sessions|tls|security|health|hardware|network|sites)[/"'"'"'?]'; \
    HITS=$(grep -oE "$PATTERN" /app/build/static/js/*.js 2>/dev/null | sort -u || true); \
    if [ -n "$HITS" ]; then \
      echo ""; \
      echo "==============================================================="; \
      echo "❌  BUILD REFUSÉ — URL API absolue détectée dans le bundle"; \
      echo "==============================================================="; \
      echo "$HITS"; \
      echo ""; \
      echo "Cause probable : REACT_APP_BACKEND_URL non vide au moment du"; \
      echo "build, ou URL absolue hardcodée dans le code source."; \
      echo "==============================================================="; \
      exit 1; \
    fi; \
    echo "✅  v1.0-rc4.5 · Bundle propre : URLs API 100% relatives"

# ─── Stage 2 : runtime Nginx ──────────────────────────────────────────
FROM nginx:1.27-alpine

# Dépendances runtime : openssl (auto-cert), curl (healthcheck), bash (entrypoint)
RUN apk add --no-cache openssl curl bash

# SPA build
COPY --from=builder /app/build /usr/share/nginx/html

# Config Nginx (reverse proxy /api /ws + HTTPS + SPA fallback)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Entrypoint auto-cert TLS (dossier /docker-entrypoint.d/ est exécuté par
# l'image officielle nginx AVANT de lancer nginx -g 'daemon off;')
COPY docker-entrypoint.sh /docker-entrypoint.d/10-mgvms-tls.sh
RUN chmod +x /docker-entrypoint.d/10-mgvms-tls.sh

EXPOSE 80
EXPOSE 443

HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
    CMD curl -fs -o /dev/null http://localhost/ || exit 1

# CMD hérité de l'image nginx : `nginx -g 'daemon off;'`
