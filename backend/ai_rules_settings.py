"""v3.23 · Config armement + règles d'alertes IA — extrait de pipeline_v2/scenarios.py.

Chantier séparation pipeline IA / serveur API (priorité #1), étape 2a.
Ces fonctions ne touchent AUCUN état mutable par le pipeline en mémoire —
seulement des constantes fixes et des lectures/écritures directes dans
`db.settings` (clés `arming_schedule` / `ai_alert_rules`). Elles n'avaient
donc aucune raison de vivre dans `pipeline_v2/` (qui deviendra un package
pipeline-only, non importable depuis le process API après la scission) :
extraites ici pour que les endpoints HTTP (`routers.py::/ai/arming`,
`/ai/alert-rules`) n'aient plus besoin d'importer `ai_engine`/`pipeline_v2`
juste pour lire de la configuration.

`pipeline_v2/scenarios.py` importe ces mêmes fonctions d'ici pour son
évaluation temps réel (`_evaluate_scenarios`) — comportement inchangé,
seul l'emplacement du code a bougé.
"""
from __future__ import annotations

from datetime import datetime

from database import db

DEFAULT_SCENARIOS = {
    "intrusion_nocturne": {"enabled": True, "severity": "critical", "night_start": 22, "night_end": 6,
                           "label": "Intrusion / effraction possible (présence nocturne)"},
    "rodeur": {"enabled": True, "severity": "warning", "consecutive": 3,
               "label": "Comportement suspect (personne qui s'attarde)"},
    "attroupement": {"enabled": True, "severity": "warning", "min_persons": 4,
                     "label": "Attroupement de personnes"},
    "vive_allure": {"enabled": True, "severity": "warning", "motion_pct": 12.0,
                    "label": "Véhicule à vive allure"},
    "collision": {"enabled": True, "severity": "critical", "iou": 0.15,
                  "label": "Collision possible entre véhicules (accident)"},
    "enfant_route": {"enabled": True, "severity": "critical", "ratio": 0.55,
                     "label": "Enfant possible sur la chaussée"},
    "vol_vehicule": {"enabled": True, "severity": "critical", "night_start": 22, "night_end": 6,
                     "label": "Vol / cambriolage possible (personne près d'un véhicule la nuit)"},
}

DEFAULT_ARMING = {"mode": "always", "days": [0, 1, 2, 3, 4, 5, 6], "start_h": 0, "end_h": 24}

# v3.23 · Idem pour les seuils QoS (pipeline_v2/qos_alerts.py) — constante
# figée, jamais mutée à l'exécution (les seuils "courants" vivent dans
# db.settings, cette constante n'est qu'un jeu de valeurs par défaut).
DEFAULT_QOS_THRESHOLDS = {
    "pipeline_total_ms": 200.0,
    "yolo_ms": 50.0,
    "tracking_ms": 5.0,
    "anpr_ms": 120.0,
    "fps_min": 5.0,
    "ram_percent": 85.0,
    "gpu_vram_percent": 90.0,
}


async def _get_scenario_rules() -> dict:
    doc = await db.settings.find_one({"key": "ai_alert_rules"}, {"_id": 0})
    rules = {k: dict(v) for k, v in DEFAULT_SCENARIOS.items()}
    if doc:
        for key, override in (doc.get("value") or {}).items():
            if key in rules and isinstance(override, dict):
                rules[key].update(override)
    return rules


async def get_arming_config() -> dict:
    doc = await db.settings.find_one({"key": "arming_schedule"}, {"_id": 0})
    return {**DEFAULT_ARMING, **((doc or {}).get("value") or {})}


async def _is_armed(now: datetime) -> bool:
    cfg = await get_arming_config()
    if cfg["mode"] == "off":
        return False
    if cfg["mode"] == "always":
        return True
    if now.weekday() not in (cfg.get("days") or []):
        return False
    h, s, e = now.hour, int(cfg["start_h"]), int(cfg["end_h"])
    return s <= h < e if s < e else (h >= s or h < e)
