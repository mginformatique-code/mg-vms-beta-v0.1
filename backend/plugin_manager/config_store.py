"""Config store persistant pour plugins (chapitre 11 §11.2.3 · ctx.config).

Persistence simple JSON file → `/app/backend/data/plugin_configs.json`.
Structure :

```json
{
  "plate-recognizer": {"api_token": "gAAAA...", "regions": ["fr"]},
  "openalpr":         {"secret_key": "gAAAA..."},
  "paddle-ocr":       {"lang": "en", "gpu": false}
}
```

**Chiffrement Fernet (P2, Feb 2026)** : les valeurs des champs sensibles
(clé contient `password`, `token`, `secret`, `api_key`, `apikey`, `webhook`,
`bot_token`, `smtp_pass`) sont chiffrées à l'écriture et déchiffrées à la
lecture — transparente pour les plugins qui reçoivent la config en clair via
`ctx.config`. Un token Fernet commence par `gAAAAA` : la lecture des anciens
fichiers non chiffrés reste rétro-compatible (les valeurs "chargent en clair").
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger("plugin_config_store")

CONFIG_PATH = Path("/app/backend/data/plugin_configs.json")

# Champs considérés sensibles → chiffrés en repos
SENSITIVE_KEY_MARKERS = ("password", "token", "secret", "api_key", "apikey",
                          "webhook", "bot_token", "smtp_pass", "smtp_password",
                          "private_key")


def _is_sensitive(key: str) -> bool:
    k = (key or "").lower()
    return any(m in k for m in SENSITIVE_KEY_MARKERS)


def _encrypt_config(cfg: dict) -> dict:
    """Chiffre les champs sensibles au premier niveau. Non-strings laissés tels quels."""
    from crypto_utils import encrypt_secret, is_encrypted
    out = {}
    for k, v in (cfg or {}).items():
        if isinstance(v, str) and v and _is_sensitive(k) and not is_encrypted(v):
            out[k] = encrypt_secret(v)
        else:
            out[k] = v
    return out


def _decrypt_config(cfg: dict) -> dict:
    """Déchiffre les champs sensibles au premier niveau."""
    from crypto_utils import decrypt_secret, is_encrypted
    out = {}
    for k, v in (cfg or {}).items():
        if isinstance(v, str) and v and _is_sensitive(k) and is_encrypted(v):
            out[k] = decrypt_secret(v)
        else:
            out[k] = v
    return out


class PluginConfigStore:
    """Store thread-safe de la configuration utilisateur des plugins.

    Les secrets (password, token, api_key, ...) sont chiffrés au repos via Fernet.
    Les getters retournent la config en clair.
    """

    def __init__(self, path: Path = CONFIG_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict = {}
        self._load()

    def _load(self):
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
                logger.info("plugin_configs.loaded plugins=%s", list(self._data.keys()))
        except Exception as e:
            logger.warning("plugin_configs.load_error err=%s", e)
            self._data = {}

    def _persist(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("plugin_configs.save_error err=%s", e)

    def get(self, name: str) -> dict:
        """Retourne la config du plugin en clair (secrets déchiffrés)."""
        with self._lock:
            return _decrypt_config(self._data.get(name, {}))

    def get_encrypted(self, name: str) -> dict:
        """Retourne la config brute (secrets restent chiffrés) — pour l'UI qui
        veut afficher `••••` sans exposer les valeurs en clair."""
        with self._lock:
            return dict(self._data.get(name, {}))

    def set(self, name: str, config: dict) -> dict:
        """Remplace intégralement la config du plugin. Chiffre les champs sensibles.
        Retourne la nouvelle config **en clair** pour usage immédiat."""
        with self._lock:
            self._data[name] = _encrypt_config(config or {})
            self._persist()
            return _decrypt_config(self._data[name])

    def update(self, name: str, patch: dict) -> dict:
        """Merge partiel avec la config existante. Chiffre les nouveaux secrets."""
        with self._lock:
            current = dict(self._data.get(name, {}))
            current.update(_encrypt_config(patch or {}))
            self._data[name] = current
            self._persist()
            return _decrypt_config(current)

    def delete(self, name: str) -> None:
        with self._lock:
            if name in self._data:
                del self._data[name]
                self._persist()

    def all(self) -> dict:
        """Retourne toutes les configs **en clair** (secrets déchiffrés)."""
        with self._lock:
            return {k: _decrypt_config(v) for k, v in self._data.items()}


store = PluginConfigStore()
