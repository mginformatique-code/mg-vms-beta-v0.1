"""Config store persistant pour plugins (chapitre 11 §11.2.3 · ctx.config).

Persistence simple JSON file → `/app/backend/data/plugin_configs.json`.
Structure :

```json
{
  "plate-recognizer": {"api_token": "abc123", "regions": ["fr"]},
  "openalpr":         {"secret_key": "sk_..."},
  "paddle-ocr":       {"lang": "en", "gpu": false}
}
```

En v3.0 : chaque plugin aura son namespace DB isolé (`db.plugin_data.{name}`)
avec chiffrement Fernet automatique sur les champs `password`/`api_key`/`token`.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("plugin_config_store")

CONFIG_PATH = Path("/app/backend/data/plugin_configs.json")


class PluginConfigStore:
    """Store thread-safe de la configuration utilisateur des plugins."""

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
        """Retourne la config du plugin (dict vide si absent)."""
        with self._lock:
            return dict(self._data.get(name, {}))

    def set(self, name: str, config: dict) -> dict:
        """Remplace intégralement la config du plugin. Retourne la nouvelle config."""
        with self._lock:
            self._data[name] = dict(config or {})
            self._persist()
            return dict(self._data[name])

    def update(self, name: str, patch: dict) -> dict:
        """Merge partiel avec la config existante."""
        with self._lock:
            current = dict(self._data.get(name, {}))
            current.update(patch or {})
            self._data[name] = current
            self._persist()
            return dict(current)

    def delete(self, name: str) -> None:
        with self._lock:
            if name in self._data:
                del self._data[name]
                self._persist()

    def all(self) -> dict:
        with self._lock:
            return {k: dict(v) for k, v in self._data.items()}


store = PluginConfigStore()
