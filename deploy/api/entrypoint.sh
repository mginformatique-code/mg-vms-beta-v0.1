#!/bin/sh
set -e
echo "[MG-VMS API] Migrations Alembic..."
alembic upgrade head
echo "[MG-VMS API] Démarrage Uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers "${API_WORKERS:-4}"
