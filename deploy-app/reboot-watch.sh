#!/bin/bash
# MG-VMS · surveille la demande de redémarrage déposée par le backend
# (menu Paramètres → Système) et redémarre la machine hôte elle-même.
#
# Le conteneur backend n'a jamais d'accès direct à Docker ni à l'hôte
# (pas de socket Docker monté, pas de privilèges élevés) — il se contente
# de déposer un fichier marqueur dans /logs (monté en écriture, voir
# docker-compose.yml). Ce script tourne sur l'HÔTE, hors conteneur, via
# le timer systemd mgvms-reboot-watch.timer (toutes les minutes).
set -euo pipefail

FLAG="${LOGS_PATH:-/mnt/storage/logs}/host-reboot-requested"

if [ -f "$FLAG" ]; then
  logger -t mgvms-reboot-watch "Redémarrage MG-VMS déclenché : $(cat "$FLAG")"
  rm -f "$FLAG"
  systemctl reboot
fi
