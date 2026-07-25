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


@dataclass
class PluginContext:
    """Contexte injecté au plugin. En v2.30 PoC : simple. En v3.0 : sandbox."""

    plugin_name: str
    version: str
    config: dict = field(default_factory=dict)
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("plugin"))
    gpu: GPUInfo = field(default_factory=GPUInfo)
    capabilities: list = field(default_factory=list)

    # État déclaré par le plugin après on_load / on_config_change
    # Valeurs : "ready" | "not_configured" | "missing_dependency" | "error" | "disabled"
    state: str = "ready"
    state_message: Optional[str] = None

    # Note v3.0 : ajouter self.db (namespace isolé), self.emit_event, self.call_plugin

    def has_capability(self, cap: str) -> bool:
        """Retourne True si la capability est déclarée dans le manifest."""
        return cap in self.capabilities or "admin" in self.capabilities

    def set_state(self, state: str, message: Optional[str] = None) -> None:
        """Le plugin déclare son état. Le bus reflète cet état pour le dispatch."""
        self.state = state
        self.state_message = message
