"""Camera API · Registry des providers.

Résolution : `provider_id` explicite > devine par `manufacturer` > "reolink" par
défaut si `/cgi-bin/api.cgi` répond (heuristique light — le vrai discovery se
fait dans routes/camera_api.py::discover).
"""
from __future__ import annotations

from typing import Type

from .base import CameraApiProvider
from .exceptions import ProviderNotFound

_REGISTRY: dict[str, Type[CameraApiProvider]] = {}


def register_provider(cls: Type[CameraApiProvider]) -> Type[CameraApiProvider]:
    """Décorateur d'enregistrement — le champ `cls.name` est la clé du registry."""
    if not cls.name or cls.name == "base":
        raise ValueError(f"Provider {cls.__name__} doit définir `name` (ex. 'reolink')")
    _REGISTRY[cls.name.lower()] = cls
    return cls


def list_providers() -> list[str]:
    _ensure_loaded()
    return sorted(_REGISTRY.keys())


def resolve_provider(*, provider_id: str = "", manufacturer: str = "",
                      model: str = "") -> Type[CameraApiProvider]:
    """Sélectionne la classe provider. Ordre :
        1. provider_id explicite (ex. "reolink")
        2. manufacturer (case-insensitive)
        3. modèle contenant un mot-clé constructeur connu
    Lève ProviderNotFound si aucun match.
    """
    _ensure_loaded()
    if provider_id:
        cls = _REGISTRY.get(provider_id.lower())
        if cls is None:
            raise ProviderNotFound(
                f"provider '{provider_id}' inconnu — disponibles : {list_providers()}")
        return cls
    if manufacturer:
        cls = _REGISTRY.get(manufacturer.lower().strip())
        if cls:
            return cls
    hay = f"{manufacturer} {model}".lower()
    for known in _REGISTRY:
        if known in hay:
            return _REGISTRY[known]
    raise ProviderNotFound(
        f"impossible d'auto-détecter le provider (manufacturer='{manufacturer}', "
        f"model='{model}') — précisez `api_provider` sur la caméra")


def _ensure_loaded() -> None:
    """Import différé pour éviter les cycles + garantir que les décorateurs
    `@register_provider` ont bien été évalués."""
    if _REGISTRY:
        return
    # Chargement explicite — Reolink (Vague 1), Dahua + Hikvision (Vague 2,
    # v3.1.5 : matériel réel disponible pour test côté utilisateur).
    from .providers import dahua, hikvision, reolink  # noqa: F401
