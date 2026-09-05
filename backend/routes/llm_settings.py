"""v3.19 · Configuration LLM (recherche IA avancée) — menu admin.

Remplace la clé cloud EMERGENT_LLM_KEY (voir smart_search.py) par une
instance Qwen auto-hébergée, exposée en WAN via un domaine dédié
(ia.mginformatique.com, reverse proxy) — pensé pour un déploiement
client simple : un menu admin, une URL, une clé API, un switch, pas
d'édition manuelle de fichier .env par site.

L'API distante est appelée au format OpenAI-compatible (chat
completions) — convention standard supportée par Ollama/Open WebUI.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_role, log_audit
from database import db
from crypto_utils import encrypt_secret, decrypt_secret

llm_settings_router = APIRouter(prefix="/api/settings/llm", tags=["llm-settings"])

_DEFAULT_BASE_URL = "https://ia.mginformatique.com"
_DEFAULT_MODEL = "qwen2.5"


class LlmConfigIn(BaseModel):
    enabled: bool = False
    base_url: str = _DEFAULT_BASE_URL
    model: str = _DEFAULT_MODEL
    api_key: str = ""
    # v3.21 · La même connexion Qwen alimente 3 fonctionnalités distinctes
    # (recherche IA, dédoublonnage véhicule, réglage ANPR auto) mais
    # jusqu'ici une seule d'entre elles était visible/pilotable depuis ce
    # menu — les deux autres tournaient silencieusement dès que `enabled`
    # était actif, sans réglage propre. Deux interrupteurs dédiés, chacun
    # nécessitant en plus que `enabled` (la connexion elle-même) le soit.
    dedup_enabled: bool = False
    anpr_tuning_enabled: bool = False
    # v3.26 · Auto-approbation des suggestions de dédoublonnage — demande
    # explicite : approuver automatiquement TOUTES les suggestions en
    # attente à intervalle régulier (30min/1h/etc), sans validation
    # manuelle. N'a d'effet que si `dedup_enabled` l'est aussi (voir
    # vehicle_dedup.py::dedup_auto_approve_loop).
    dedup_auto_approve_enabled: bool = False
    dedup_auto_approve_interval_min: int = 60
    # v3.44 · IA anomalies véhicule (menu dédié + corrélations convoi/vague,
    # voir vehicle_anomaly_ai.py) — même convention que les autres switchs
    # dédiés ci-dessus.
    anomaly_ai_enabled: bool = False
    # v3.45 · Couleur véhicule via modèle VISION (qwen2.5vl) — distinct du
    # `model` texte ci-dessus (utilisé par dedup/anpr_tuning/anomaly_ai) :
    # aucun des modèles texte de ce serveur ne peut voir une image. Même
    # connexion (base_url/api_key) que le reste, juste un nom de modèle
    # différent. Voir vehicle_color_ai.py.
    vision_model: str = "qwen2.5vl:7b"
    color_ai_enabled: bool = False
    # v3.46 · Identification marque véhicule — même modèle vision que la
    # couleur, interrupteur dédié séparé (voir vehicle_make_ai.py).
    make_ai_enabled: bool = False


async def _load_raw() -> dict:
    doc = await db.settings.find_one({"key": "llm_config"}, {"_id": 0})
    return (doc or {}).get("value") or {}


def _mask(v: dict) -> dict:
    """Ne renvoie jamais la clé API en clair — même convention que
    notifications.py (has_<secret> + valeur masquée)."""
    return {
        "enabled": bool(v.get("enabled", False)),
        "base_url": v.get("base_url") or _DEFAULT_BASE_URL,
        "model": v.get("model") or _DEFAULT_MODEL,
        "api_key": "",
        "has_api_key": bool(v.get("api_key")),
        "dedup_enabled": bool(v.get("dedup_enabled", False)),
        "anpr_tuning_enabled": bool(v.get("anpr_tuning_enabled", False)),
        "dedup_auto_approve_enabled": bool(v.get("dedup_auto_approve_enabled", False)),
        "dedup_auto_approve_interval_min": int(v.get("dedup_auto_approve_interval_min") or 60),
        "anomaly_ai_enabled": bool(v.get("anomaly_ai_enabled", False)),
        "vision_model": v.get("vision_model") or "qwen2.5vl:7b",
        "color_ai_enabled": bool(v.get("color_ai_enabled", False)),
        "make_ai_enabled": bool(v.get("make_ai_enabled", False)),
    }


@llm_settings_router.get("")
async def get_llm_config(user: dict = Depends(require_role("admin"))):
    return _mask(await _load_raw())


@llm_settings_router.put("")
async def put_llm_config(data: LlmConfigIn, user: dict = Depends(require_role("admin"))):
    existing = await _load_raw()
    # Clé API vide dans le payload = conserver l'existante (ne jamais écraser
    # un secret déjà enregistré par une valeur vide venue du frontend masqué).
    api_key_enc = encrypt_secret(data.api_key) if data.api_key else existing.get("api_key", "")
    value = {
        "enabled": data.enabled,
        "base_url": (data.base_url or "").strip().rstrip("/") or _DEFAULT_BASE_URL,
        "model": (data.model or "").strip() or _DEFAULT_MODEL,
        "api_key": api_key_enc,
        "dedup_enabled": data.dedup_enabled,
        "anpr_tuning_enabled": data.anpr_tuning_enabled,
        "dedup_auto_approve_enabled": data.dedup_auto_approve_enabled,
        # Garde-fou : jamais en dessous de 5 min, quel que soit ce qui est
        # envoyé (un intervalle trop court transformerait la boucle de poll
        # en quasi-temps réel, aucun cas d'usage légitime).
        "dedup_auto_approve_interval_min": max(5, int(data.dedup_auto_approve_interval_min or 60)),
        "anomaly_ai_enabled": data.anomaly_ai_enabled,
        "vision_model": (data.vision_model or "").strip() or "qwen2.5vl:7b",
        "color_ai_enabled": data.color_ai_enabled,
        "make_ai_enabled": data.make_ai_enabled,
    }
    await db.settings.update_one({"key": "llm_config"}, {"$set": {"key": "llm_config", "value": value}}, upsert=True)
    await log_audit(user, "llm_config_updated", value["base_url"])
    return _mask(value)


async def is_feature_enabled(feature: str) -> bool:
    """v3.21 · Utilisé par vehicle_dedup.py et anpr_tuning.py — `feature`
    vaut "dedup_enabled" ou "anpr_tuning_enabled". Exige la connexion LLM
    globale ET l'interrupteur dédié à la fonctionnalité, tous les deux actifs."""
    v = await _load_raw()
    return bool(v.get("enabled")) and bool(v.get(feature))


async def get_dedup_auto_approve_settings() -> dict:
    """Utilisé par vehicle_dedup.py::dedup_auto_approve_loop. Ne vérifie PAS
    `dedup_enabled`/`enabled` ici — reste la responsabilité de l'appelant
    (même convention que is_feature_enabled, qui les vérifie déjà pour la
    génération des suggestions elles-mêmes)."""
    v = await _load_raw()
    return {
        "enabled": bool(v.get("dedup_auto_approve_enabled", False)),
        "interval_min": max(5, int(v.get("dedup_auto_approve_interval_min") or 60)),
    }


async def get_active_llm_config() -> Optional[dict]:
    """Utilisé par smart_search.py — config déchiffrée si le switch est actif,
    None sinon (déclenche le repli existant SMART_SEARCH_LLM_NOT_CONFIGURED)."""
    v = await _load_raw()
    if not v.get("enabled") or not v.get("base_url"):
        return None
    return {
        "base_url": v["base_url"],
        "model": v.get("model") or _DEFAULT_MODEL,
        "api_key": decrypt_secret(v.get("api_key", "")),
    }


async def get_vision_llm_config() -> Optional[dict]:
    """Utilisé par vehicle_color_ai.py ET vehicle_make_ai.py — même connexion
    que get_active_llm_config mais avec le modèle VISION dédié
    (`vision_model`), pas le modèle texte (`model`). Ne vérifie QUE la
    connexion globale (`enabled`) + `vision_model` — PAS un interrupteur de
    fonctionnalité spécifique (color_ai_enabled/make_ai_enabled), puisque
    cette config est partagée par plusieurs plugins vision distincts ;
    chaque appelant vérifie son propre `is_feature_enabled(...)` séparément
    avant d'en avoir besoin. None si la connexion ou `vision_model` manque
    — l'appelant dégrade proprement (pas de 500)."""
    v = await _load_raw()
    if not v.get("enabled") or not v.get("base_url") or not v.get("vision_model"):
        return None
    return {
        "base_url": v["base_url"],
        "model": v["vision_model"],
        "api_key": decrypt_secret(v.get("api_key", "")),
    }
