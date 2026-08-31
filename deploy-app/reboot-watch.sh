#!/bin/bash
# MG-VMS · surveille les demandes déposées par le backend depuis le menu
# "Date et heure" (redémarrage machine, changement de serveur NTP amont)
# et les exécute côté hôte.
#
# Le conteneur backend n'a jamais d'accès direct à Docker ni à l'hôte
# (pas de socket Docker monté, pas de privilèges élevés) — il se contente
# de déposer un fichier marqueur dans /logs (monté en écriture, voir
# docker-compose.yml). Ce script tourne sur l'HÔTE, hors conteneur, via
# le timer systemd mgvms-reboot-watch.timer (toutes les minutes).
set -euo pipefail

LOGS="${LOGS_PATH:-/mnt/storage/logs}"

# ── Redémarrage machine ──────────────────────────────────────────────
REBOOT_FLAG="${LOGS}/host-reboot-requested"
if [ -f "$REBOOT_FLAG" ]; then
  logger -t mgvms-reboot-watch "Redémarrage MG-VMS déclenché : $(cat "$REBOOT_FLAG")"
  rm -f "$REBOOT_FLAG"
  systemctl reboot
fi

# ── Serveur NTP amont (chrony) ───────────────────────────────────────
# v3.19 · MG-VMS sert l'heure aux caméras (voir mgvms-camera-lan.conf),
# mais doit lui-même se synchroniser sur une source fiable avant de la
# diffuser. Vide = revient au pool Debian par défaut.
NTP_FLAG="${LOGS}/host-ntp-upstream-requested"
if [ -f "$NTP_FLAG" ]; then
  UPSTREAM=$(tr -d '\r\n' < "$NTP_FLAG")
  logger -t mgvms-reboot-watch "Changement serveur NTP amont demandé : ${UPSTREAM:-<défaut Debian>}"
  if [ -n "$UPSTREAM" ]; then
    echo "pool ${UPSTREAM} iburst" > /etc/chrony/conf.d/mgvms-upstream.conf
  else
    rm -f /etc/chrony/conf.d/mgvms-upstream.conf
  fi
  systemctl restart chrony
  rm -f "$NTP_FLAG"
fi
