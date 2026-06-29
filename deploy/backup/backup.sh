#!/bin/sh
# MG-VMS — sauvegarde quotidienne (artefact de prod).
set -e
TS=$(date +%Y%m%d-%H%M%S)
echo "[backup] dump PostgreSQL..."
pg_dump "$DATABASE_URL" | gzip > "/tmp/db-$TS.sql.gz"
echo "[backup] upload MinIO/S3..."
aws --endpoint-url "$S3_ENDPOINT" s3 cp "/tmp/db-$TS.sql.gz" "s3://backups/db-$TS.sql.gz"
# Config + enregistrements (rsync/aws s3 sync) à compléter selon le stockage cible.
echo "[backup] terminé: $TS"
