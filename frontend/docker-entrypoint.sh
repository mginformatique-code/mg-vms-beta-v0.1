#!/usr/bin/env bash
# ==============================================================================
# MG-VMS · Frontend auto-cert TLS · v1.0
# ==============================================================================
# Exécuté par le launcher nginx officiel (dossier /docker-entrypoint.d) AVANT
# de lancer nginx -g 'daemon off;'.
#
# Comportement :
#   - Si /etc/nginx/certs/fullchain.pem + privkey.pem existent → RIEN.
#     L'utilisateur peut fournir ses propres certificats (Let's Encrypt,
#     wildcard maison, etc.) en montant /mnt/storage/certs dans le compose.
#   - Sinon → génère un certificat self-signed 2048 bits valable 3650 jours
#     avec CN=$MGVMS_HOSTNAME (ou 'mg-vms.local' par défaut).
#
# Pour REGÉNÉRER : vider le dossier /mnt/storage/certs sur l'hôte puis
#   docker compose restart frontend
# Pour REMPLACER : copier ses .pem/.key à la place et redémarrer.

set -euo pipefail

CERT_DIR="${CERT_DIR:-/etc/nginx/certs}"
CN="${MGVMS_HOSTNAME:-mg-vms.local}"

mkdir -p "$CERT_DIR"

if [ -s "$CERT_DIR/fullchain.pem" ] && [ -s "$CERT_DIR/privkey.pem" ]; then
    echo "[mgvms-tls] Certificat existant détecté ($CERT_DIR) — swap OK, on garde."
    exit 0
fi

echo "[mgvms-tls] Aucun certificat trouvé — génération self-signed (CN=$CN, 3650j)"

openssl req -x509 -nodes -newkey rsa:2048 \
    -days 3650 \
    -subj "/C=FR/ST=France/L=Paris/O=MG-VMS/OU=Auto/CN=$CN" \
    -addext "subjectAltName=DNS:$CN,DNS:localhost,IP:127.0.0.1" \
    -keyout "$CERT_DIR/privkey.pem" \
    -out    "$CERT_DIR/fullchain.pem"

chmod 600 "$CERT_DIR/privkey.pem"
chmod 644 "$CERT_DIR/fullchain.pem"

echo "[mgvms-tls] Certificat self-signed prêt (remplaçable à chaud)."
