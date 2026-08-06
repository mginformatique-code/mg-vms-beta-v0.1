"""Test fixtures — charge le .env backend pour les tests offline (Fernet, DB, JWT).

Active `TESTING=1` de manière automatique pour tous les tests afin de
neutraliser les rate-limits (SecurityMiddleware) et le verrou brute-force
d'authentification (auth._check_lockout). Sans cette bypass, les campagnes
parallèles se croisaient sur le même IP/email et déclenchaient des 429/423.
"""
import os
import sys
from pathlib import Path

# Ensure backend modules (auth, security, database, ...) are importable
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


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
os.environ["TESTING"] = "1"
