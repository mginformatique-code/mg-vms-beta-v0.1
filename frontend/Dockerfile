# ==============================================================================
# MG-VMS · Frontend · Production Dockerfile v1.0
# ==============================================================================
# Multi-stage : build React (node:20) puis serve via nginx (alpine).
# L'image contient l'entrypoint auto-cert : au démarrage, si aucun certificat
# TLS n'est présent dans /etc/nginx/certs/ un self-signed est généré.
# L'utilisateur peut swapper à chaud en remplaçant fullchain.pem/privkey.pem.

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

# Build de production (variable REACT_APP_BACKEND_URL injectée à build-time
# via docker-compose args)
ARG REACT_APP_BACKEND_URL=""
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
RUN yarn build

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
