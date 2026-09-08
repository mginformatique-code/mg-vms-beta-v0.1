#!/bin/bash
# MG-VMS · Paramètres réseau (Réseau → Paramètres réseau) : lit l'état
# réseau réel de la MACHINE/VM hôte et applique les changements demandés
# depuis l'UI, avec un filet de sécurité auto-revert (comme `netplan try`).
#
# Même logique que reboot-watch.sh / container-status-watch.sh : le
# conteneur backend n'a JAMAIS d'accès direct au réseau de l'hôte (pas de
# NET_ADMIN, pas de host networking) — il dépose une simple DEMANDE dans
# /logs (host-network-requested.json) et relit un INSTANTANÉ écrit par ce
# script (network_status.json). Ce script tourne sur l'HÔTE, hors
# conteneur, via le timer systemd mgvms-network-watch.timer (15s).
#
# Sécurité : changer l'IP/la passerelle/le DNS d'une machine à distance
# peut couper l'accès à cette machine si la nouvelle config est mauvaise.
# Le changement est donc appliqué avec un délai de confirmation
# (NETWORK_CONFIRM_TIMEOUT_S, 90s) : si personne ne confirme depuis
# l'interface MG-VMS dans ce délai (précisément parce que la connexion
# vient peut-être d'être coupée par le changement), la config précédente
# est restaurée automatiquement.
set -euo pipefail

LOGS="${LOGS_PATH:-/mnt/storage/logs}"
STATUS_OUT="${LOGS}/network_status.json"
REQUEST_IN="${LOGS}/host-network-requested.json"
PENDING="${LOGS}/host-network-pending-confirm.json"
CONFIRM_FLAG="${LOGS}/host-network-confirm.flag"
CONFIRM_TIMEOUT_S=90

mkdir -p "$LOGS"

# ── Lit l'état IPv4 effectif de l'interface de la route par défaut ────
read_current() {
  local iface conn ip_cidr gateway dns_csv method ip prefix
  iface=$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')
  if [ -z "$iface" ]; then
    jq -n '{interface:null,connection:null,method:null,ip:null,prefix:null,gateway:null,dns:[]}'
    return
  fi
  conn=$(nmcli -g GENERAL.CONNECTION device show "$iface" 2>/dev/null || true)
  ip_cidr=$(nmcli -g IP4.ADDRESS device show "$iface" 2>/dev/null | head -1 || true)
  gateway=$(nmcli -g IP4.GATEWAY device show "$iface" 2>/dev/null || true)
  dns_csv=$(nmcli -g IP4.DNS device show "$iface" 2>/dev/null | paste -sd, - || true)
  method=$(nmcli -g ipv4.method con show "$conn" 2>/dev/null || true)
  ip="${ip_cidr%%/*}"
  prefix="${ip_cidr##*/}"
  [ "$prefix" = "$ip_cidr" ] && prefix=""
  jq -n --arg iface "$iface" --arg conn "$conn" --arg method "$method" \
        --arg ip "$ip" --arg prefix "$prefix" --arg gateway "$gateway" --arg dns_csv "$dns_csv" '
    {
      interface: $iface, connection: $conn, method: $method,
      ip: $ip, prefix: ($prefix | select(. != "") | tonumber? // null),
      gateway: $gateway,
      dns: ($dns_csv | select(. != "") | split(",") // [])
    }'
}

# ── Applique une config IPv4 (statique ou DHCP) à la connexion active ──
# $1 = JSON {method, ip, prefix, gateway, dns:[...]}, $2 = nom connexion
apply_config() {
  local cfg="$1" conn="$2" method ip prefix gateway dns_csv
  method=$(echo "$cfg" | jq -r '.method')
  if [ "$method" = "manual" ]; then
    ip=$(echo "$cfg" | jq -r '.ip')
    prefix=$(echo "$cfg" | jq -r '.prefix')
    gateway=$(echo "$cfg" | jq -r '.gateway')
    dns_csv=$(echo "$cfg" | jq -r '.dns | join(",")')
    nmcli con mod "$conn" ipv4.method manual ipv4.addresses "${ip}/${prefix}" \
      ipv4.gateway "$gateway" ipv4.dns "$dns_csv"
  else
    nmcli con mod "$conn" ipv4.method auto ipv4.addresses "" ipv4.gateway "" ipv4.dns ""
  fi
  nmcli con up "$conn" >/dev/null 2>&1 || true
}

CURRENT=$(read_current)
TMP="${STATUS_OUT}.tmp.$$"

# ── 1. Confirmation en attente : expirée -> revert, confirmée -> clôture ─
if [ -f "$PENDING" ]; then
  DEADLINE=$(jq -r '.deadline' "$PENDING")
  NOW_EPOCH=$(date +%s)
  DEADLINE_EPOCH=$(date -d "$DEADLINE" +%s 2>/dev/null || echo 0)
  if [ -f "$CONFIRM_FLAG" ]; then
    logger -t mgvms-network-watch "Nouvelle config réseau confirmée par l'admin — conservée."
    rm -f "$PENDING" "$CONFIRM_FLAG"
  elif [ "$NOW_EPOCH" -ge "$DEADLINE_EPOCH" ]; then
    CONN=$(echo "$CURRENT" | jq -r '.connection')
    BACKUP=$(jq -c '.backup' "$PENDING")
    logger -t mgvms-network-watch "Non confirmée dans les ${CONFIRM_TIMEOUT_S}s — restauration de la config précédente."
    apply_config "$BACKUP" "$CONN"
    rm -f "$PENDING"
    CURRENT=$(read_current)
  fi
fi

# ── 2. Nouvelle demande (uniquement si rien n'est déjà en attente) ─────
if [ -f "$REQUEST_IN" ] && [ ! -f "$PENDING" ]; then
  REQUESTED=$(cat "$REQUEST_IN")
  CONN=$(echo "$CURRENT" | jq -r '.connection')
  if [ -n "$CONN" ] && [ "$CONN" != "null" ]; then
    logger -t mgvms-network-watch "Nouvelle config réseau demandée depuis MG-VMS — application avec confirmation sous ${CONFIRM_TIMEOUT_S}s."
    DEADLINE=$(date -u -d "+${CONFIRM_TIMEOUT_S} seconds" '+%Y-%m-%dT%H:%M:%SZ')
    jq -n --argjson backup "$CURRENT" --arg deadline "$DEADLINE" --argjson req "$REQUESTED" \
      '{deadline:$deadline, requested_at: (now|todate), backup:{method:$backup.method, ip:$backup.ip, prefix:$backup.prefix, gateway:$backup.gateway, dns:$backup.dns}, requested:$req}' \
      > "${PENDING}.tmp.$$"
    mv -f "${PENDING}.tmp.$$" "$PENDING"
    apply_config "$REQUESTED" "$CONN"
    CURRENT=$(read_current)
  else
    logger -t mgvms-network-watch "Demande de config réseau ignorée : connexion active introuvable."
  fi
  rm -f "$REQUEST_IN"
fi

# ── 3. Instantané pour le backend ──────────────────────────────────────
PENDING_JSON="null"
if [ -f "$PENDING" ]; then
  NOW_EPOCH=$(date +%s)
  DEADLINE_EPOCH=$(date -d "$(jq -r '.deadline' "$PENDING")" +%s 2>/dev/null || echo 0)
  REMAINING=$(( DEADLINE_EPOCH - NOW_EPOCH ))
  [ "$REMAINING" -lt 0 ] && REMAINING=0
  PENDING_JSON=$(jq -c --argjson remaining "$REMAINING" '. + {seconds_remaining:$remaining}' "$PENDING")
fi
jq -n --argjson current "$CURRENT" --argjson pending "$PENDING_JSON" --arg updated_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  '{current:$current, pending_confirm:$pending, updated_at:$updated_at}' > "$TMP"
chmod 0644 "$TMP"
mv -f "$TMP" "$STATUS_OUT"
