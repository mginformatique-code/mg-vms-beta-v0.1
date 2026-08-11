#!/bin/bash
# MG-VMS · Réinstalle MediaMTX dans le pod dev (à relancer après un fork,
# /opt n'étant pas persisté). Usage : bash /app/scripts/setup_mediamtx_dev.sh
set -e
ARCH=$(uname -m)
[ "$ARCH" = "aarch64" ] && MTX_ARCH=arm64 || MTX_ARCH=amd64
if [ ! -x /opt/mediamtx/mediamtx ]; then
  mkdir -p /opt/mediamtx
  curl -sL -o /tmp/mediamtx.tar.gz \
    "https://github.com/bluenviron/mediamtx/releases/download/v1.15.5/mediamtx_v1.15.5_linux_${MTX_ARCH}.tar.gz"
  tar xzf /tmp/mediamtx.tar.gz -C /opt/mediamtx mediamtx
fi
cp /app/deploy-app/mediamtx-dev.yml /opt/mediamtx/mediamtx-dev.yml
sudo supervisorctl restart mediamtx || sudo supervisorctl start mediamtx
sleep 2
curl -s http://localhost:9997/v3/config/global/get >/dev/null && echo "MediaMTX dev OK (API 9997)"
