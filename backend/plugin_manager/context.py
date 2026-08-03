"""PluginContext — injecté par le core à chaque plugin (chapitre 11 §11.2.3).

Le plugin n'accède JAMAIS directement à la DB, aux logs, à la config, au GPU
ou aux autres plugins. Toujours via ce contexte. Permet en v3.0 d'appliquer
les capabilities déclaratives (chapitre 11 §11.5.1).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class GPUInfo:
    available: bool = False
    device: str = "cpu"
    vram_total_mb: int = 0
    vram_used_mb: int = 0


class PluginDB:
    """Namespace DB isolé par plugin (P2 finalisation, Feb 2026).

    Chaque plugin accède UNIQUEMENT à une collection dédiée
    `plugin_data_{plugin_name}` — il ne peut pas lire/écrire les collections
    core (cameras, events, etc.). C'est le premier niveau d'isolation "capabilities".

    Usage dans un plugin :
        await ctx.db.insert({"key": "value"})
        docs = await ctx.db.find({"key": "value"})
        await ctx.db.update({"key": "value"}, {"$set": {"count": 1}})
        await ctx.db.delete({"key": "value"})
    """

    def __init__(self, plugin_name: str):
        self._plugin_name = plugin_name
        # Nom sanitisé pour Mongo (lettres/chiffres/_-)
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in plugin_name)
        self._collection_name = f"plugin_data_{safe}"
        self._coll = None

    def _c(self):
        if self._coll is None:
            from database import db
            self._coll = db[self._collection_name]
        return self._coll

    async def insert(self, doc: dict) -> str:
        r = await self._c().insert_one(dict(doc))
        return str(r.inserted_id)

    async def find(self, query: dict | None = None, limit: int = 1000) -> list:
        q = dict(query or {})
        return await self._c().find(q, {"_id": 0}).limit(limit).to_list(limit)

    async def find_one(self, query: dict | None = None) -> dict | None:
        return await self._c().find_one(dict(query or {}), {"_id": 0})

    async def update(self, query: dict, patch: dict) -> int:
        r = await self._c().update_many(dict(query), dict(patch))
        return r.modified_count

    async def delete(self, query: dict) -> int:
        r = await self._c().delete_many(dict(query))
        return r.deleted_count

    async def count(self, query: dict | None = None) -> int:
        return await self._c().count_documents(dict(query or {}))

    @property
    def collection_name(self) -> str:
        return self._collection_name


@dataclass
class PluginContext:
    """Contexte injecté au plugin. En v2.30 PoC : simple. En v3.0 : sandbox."""

    plugin_name: str
    version: str
    config: dict = field(default_factory=dict)
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("plugin"))
    gpu: GPUInfo = field(default_factory=GPUInfo)
    capabilities: list = field(default_factory=list)
    # DB isolée (P2) — chaque plugin a son propre namespace `plugin_data_{name}`
    db: PluginDB | None = None

    # État déclaré par le plugin après on_load / on_config_change
    # Valeurs : "ready" | "not_configured" | "missing_dependency" | "error" | "disabled"
    state: str = "ready"
    state_message: Optional[str] = None

    def has_capability(self, cap: str) -> bool:
        """Retourne True si la capability est déclarée dans le manifest."""
        return cap in self.capabilities or "admin" in self.capabilities

    def set_state(self, state: str, message: Optional[str] = None) -> None:
        """Le plugin déclare son état. Le bus reflète cet état pour le dispatch."""
        self.state = state
        self.state_message = message
