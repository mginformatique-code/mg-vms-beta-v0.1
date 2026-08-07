# ==============================================================================
# MG-VMS · Frontend · Production Dockerfile v1.0
# ==============================================================================
# Multi-stage : build React (node:20) puis serve via nginx (alpine).
# L'image contient l'entrypoint auto-cert : au démarrage, si aucun certificat
# TLS n'est présent dans /etc/nginx/certs/ un self-signed est généré.
# L'utilisateur peut swapper à chaud en remplaçant fullchain.pem/privkey.pem.

# ─── Stage 1 : build React ────────────────────────────────────────────
FROM node:20-bookworm-slim AS builder

ENV NODE_ENV=production
ENV CI=true
ENV GENERATE_SOURCEMAP=false

WORKDIR /app

COPY package.json ./
COPY yarn.lock* ./

# TEMPORAIRE : tant que le dépôt n'est pas 100 % clean sur les resolutions
# yarn, on évite --frozen-lockfile (voir docker/README.md #Yarn).
RUN yarn install \
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
