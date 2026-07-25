"""Registry des plugins — PoC v2.30 (chantier A roadmap).

En v2.30 : registre en mémoire des plugins « officiels bundle » (yolo-detection,
fast-alpr, smtp-notifier, discord-notifier, telegram-notifier, zone-analytics).

En v3.0 : découverte dynamique depuis /data/plugins/, manifest YAML, install/uninstall,
sandbox sub-process/container.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PluginInfo:
    """Représentation runtime d'un plugin — exposée via /api/plugins."""

    name: str
    display_name: str
    version: str
    description: str
    author: str = "MG-VMS Team"
    license: str = "MIT"
    categories: list = field(default_factory=list)  # ai, notification, ...
    interface: str = ""  # FrameAnalyzer, PlateRecognizer, EventConsumer
    runtime: str = "python"
    bundled: bool = True  # plugin officiel du bundle v3.0

    # État runtime
    state: str = "loaded"  # loaded | running | crashed | disabled
    enabled: bool = True
    load_error: Optional[str] = None
    load_attempts: int = 0
    last_load_ts: Optional[str] = None

    # Métriques (v3.0 sera enrichi via GPU Manager / superviseur)
    cpu_percent: Optional[float] = None
    ram_mb: Optional[float] = None
    gpu_vram_mb: Optional[float] = None
    fps: Optional[float] = None

    # Capabilities déclarées
    capabilities: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class PluginRegistry:
    """Registre en mémoire des plugins officiels (PoC v2.30)."""

    def __init__(self):
        self._plugins: dict = {}
        self._init_bundle()

    def _init_bundle(self):
        """Enregistre les 6 plugins officiels comme wrappers du code existant.

        En v2.30 : ces plugins sont des VUES sur le code existant (`ai_engine`,
        `notifications`) — ils permettent d'exposer `/api/plugins` avec des
        données réelles sans refonte immédiate.
        """
        now = datetime.now(timezone.utc).isoformat()

        bundle = [
            PluginInfo(
                name="yolo-detection",
                display_name="YOLO Object Detection",
                version="1.0.0-preview",
                description="Détection d'objets temps-réel YOLOv11 CPU/GPU (bundle officiel).",
                categories=["ai", "detection"],
                interface="FrameAnalyzer",
                capabilities=["camera.frame.read", "event.write"],
                last_load_ts=now,
            ),
            PluginInfo(
                name="fast-alpr",
                display_name="Fast-ALPR (ANPR local)",
                version="1.0.0-preview",
                description="Reconnaissance de plaques d'immatriculation CPU-ONNX (bundle officiel).",
                categories=["ai", "anpr"],
                interface="PlateRecognizer",
                capabilities=["camera.frame.read", "event.write"],
                last_load_ts=now,
            ),
            PluginInfo(
                name="smtp-notifier",
                display_name="SMTP Email Notifier",
                version="1.0.0-preview",
                description="Envoi d'alertes par email SMTP (bundle officiel).",
                categories=["notification", "integration"],
                interface="EventConsumer",
                capabilities=["event.read", "network.outbound"],
                last_load_ts=now,
            ),
            PluginInfo(
                name="discord-notifier",
                display_name="Discord Webhook Notifier",
                version="1.0.0-preview",
                description="Envoi d'alertes vers webhook Discord (bundle officiel).",
                categories=["notification", "integration"],
                interface="EventConsumer",
                capabilities=["event.read", "network.outbound"],
                last_load_ts=now,
            ),
            PluginInfo(
                name="telegram-notifier",
                display_name="Telegram Bot Notifier",
                version="1.0.0-preview",
                description="Envoi d'alertes via bot Telegram (bundle officiel).",
                categories=["notification", "integration"],
                interface="EventConsumer",
                capabilities=["event.read", "network.outbound"],
                last_load_ts=now,
            ),
            PluginInfo(
                name="zone-analytics",
                display_name="Zone Analytics (CrossLine, Zone, Loitering)",
                version="1.0.0-preview",
                description="Analytics vidéo : ligne de comptage, zone d'intrusion, loitering (bundle officiel).",
                categories=["ai", "analytics"],
                interface="FrameAnalyzer",
                capabilities=["camera.frame.read", "event.write"],
                last_load_ts=now,
            ),
        ]
        for p in bundle:
            self._plugins[p.name] = p

    def sync_from_ai_health(self, ai_health: dict) -> None:
        """Reflète l'état réel des modèles IA dans les plugins concernés.

        En v2.30 (PoC) : yolo-detection et fast-alpr sont des vues sur
        _ai_health du module ai_engine. Cela permet à /api/plugins de refléter
        la vraie santé sans réécrire l'IA.
        """
        yolo = self._plugins.get("yolo-detection")
        if yolo:
            yolo.state = "running" if ai_health.get("yolo_loaded") else "crashed"
            yolo.load_error = ai_health.get("yolo_error")
            yolo.load_attempts = ai_health.get("yolo_load_attempts", 0)
            yolo.last_load_ts = ai_health.get("yolo_last_attempt_ts")

        alpr = self._plugins.get("fast-alpr")
        if alpr:
            alpr.state = "running" if ai_health.get("alpr_loaded") else "crashed"
            alpr.load_error = ai_health.get("alpr_error")
            alpr.load_attempts = ai_health.get("alpr_load_attempts", 0)
            alpr.last_load_ts = ai_health.get("alpr_last_attempt_ts")

    def list_plugins(self) -> list:
        return [p.to_dict() for p in self._plugins.values()]

    def get(self, name: str) -> Optional[PluginInfo]:
        return self._plugins.get(name)


# Singleton
registry = PluginRegistry()
