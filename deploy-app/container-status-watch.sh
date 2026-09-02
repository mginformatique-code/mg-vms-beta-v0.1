#!/bin/bash
# MG-VMS · écrit un instantané JSON de l'état des conteneurs Docker
# (panneau "État des conteneurs" — Suivi des performances → Debug).
#
# Même logique que reboot-watch.sh : le conteneur backend n'a jamais
# d'accès direct à Docker (pas de socket Docker monté, pas de privilèges
# élevés) — ce script tourne sur l'HÔTE, hors conteneur, via le timer
# systemd mgvms-container-status-watch.timer (toutes les 10s), et écrit
# un fichier que le backend se contente de relire (/logs, déjà monté en
# écriture-lecture, voir docker-compose.yml).
set -euo pipefail

LOGS="${LOGS_PATH:-/mnt/storage/logs}"
OUT="${LOGS}/container_status.json"
TMP="${OUT}.tmp.$$"

mkdir -p "$LOGS"

CONTAINERS=$(docker ps -a --filter "network=mgvms" --format '{{.ID}}' 2>/dev/null || true)

if [ -z "$CONTAINERS" ]; then
  echo "[]" > "$TMP"
else
  # shellcheck disable=SC2086
  docker inspect $CONTAINERS 2>/dev/null | jq '[.[] | {
    name: (.Name | ltrimstr("/")),
    running: .State.Running,
    status: .State.Status,
    health: (.State.Health.Status // "n/a"),
    image: .Config.Image,
    internal_ip: (.NetworkSettings.Networks.mgvms.IPAddress // ""),
    created_at: .Created,
    started_at: .State.StartedAt,
    restart_count: .RestartCount,
    ports: (.NetworkSettings.Ports // {} | to_entries | map(select(.value != null))
            | map({container: .key, host: [.value[] | (.HostIp + ":" + .HostPort)]}))
  }]' > "$TMP" || echo "[]" > "$TMP"
fi

# Écriture atomique (le backend peut lire pendant l'écriture sinon) —
# 0644 : lisible par n'importe quel UID conteneur (le montage /logs n'a
# pas d'utilisateur commun garanti entre hôte et conteneur backend).
chmod 0644 "$TMP"
mv -f "$TMP" "$OUT"
