"""Test fixtures — charge le .env backend pour les tests offline (Fernet, DB, JWT)."""
import os
from pathlib import Path


def _load_env():
    env_file = Path("/app/backend/.env")
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_env()
