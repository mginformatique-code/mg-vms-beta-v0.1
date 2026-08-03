"""Smart Zones — Modèle de données + collection Mongo (P3, Feb 2026).

Une zone intelligente est un polygone (ou zone rectangulaire) associée à une
caméra, capable de :
- **détecter** un ou plusieurs types d'objets (`person`, `car`, `plate:AB-123-CD`, …)
- **mesurer** entrée/sortie/durée/comptage/occupation
- **déclencher** N actions vers différents actionneurs (webhook, MQTT, HA, Tuya…)

Structure Mongo (collection `smart_zones`):
```
{
  "id": "uuid",
  "name": "Entrée principale",
  "camera_id": "cam-1",
  "enabled": true,
  "polygon": [[x1,y1],[x2,y2],...],       // coords relatives [0..1] du frame
  "detect": {
      "classes": ["person","car"],         // classes YOLO ou "plate:*" pour ANPR
      "min_confidence": 0.5,
      "min_dwell_seconds": 0,               // reste dans la zone pendant N s avant trigger
      "cooldown_seconds": 60                // ne pas re-trigger avant N s
  },
  "trigger_on": ["enter","exit","present"], // events surveillés
  "actions": [
      {"type":"webhook","config":{"url":"...","method":"POST","body":{...}}},
      {"type":"mqtt","config":{"broker":"tcp://...","topic":"...","payload":"..."}},
      {"type":"home_assistant","config":{"base_url":"...","token":"...","service":"light.turn_on","data":{...}}},
      {"type":"tuya","config":{"device_id":"...","access_id":"...","access_secret":"...","commands":[...]}},
      {"type":"plugin","config":{"plugin_name":"telegram-notifier","event":{...}}}
  ],
  "last_triggered_at": "iso",
  "trigger_count": 0,
  "created_at": "iso"
}
```
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ZoneDetectConfig(BaseModel):
    classes: list[str] = Field(default_factory=list)
    min_confidence: float = 0.5
    min_dwell_seconds: int = 0
    cooldown_seconds: int = 60


class ZoneAction(BaseModel):
    """Action à déclencher — type parmi : webhook, mqtt, home_assistant, tuya, plugin, tts."""
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class SmartZoneInput(BaseModel):
    name: str
    camera_id: str
    enabled: bool = True
    polygon: list[list[float]] = Field(default_factory=list)
    detect: ZoneDetectConfig = Field(default_factory=ZoneDetectConfig)
    trigger_on: list[str] = Field(default_factory=lambda: ["enter"])
    actions: list[ZoneAction] = Field(default_factory=list)


def new_zone_doc(input_: SmartZoneInput) -> dict:
    import uuid
    return {
        "id": str(uuid.uuid4()),
        "name": input_.name,
        "camera_id": input_.camera_id,
        "enabled": input_.enabled,
        "polygon": input_.polygon,
        "detect": input_.detect.model_dump(),
        "trigger_on": input_.trigger_on,
        "actions": [a.model_dump() for a in input_.actions],
        "last_triggered_at": None,
        "trigger_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
