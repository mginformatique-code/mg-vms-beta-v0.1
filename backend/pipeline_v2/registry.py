"""Pipeline v2 · Per-Camera Graph Registry.

Chaque caméra a un **graphe d'exécution unique** compilé selon sa liste
``enabled_plugins``. Le graphe précalcule :

* Si l'étape ``detection`` est active (au moins un ``FrameAnalyzer`` activé
  et présent dans la whitelist)
* Idem pour ``tracking``, ``segmentation``, ``business`` (PipelineConsumer)
* Idem pour ``anpr`` (fast-alpr ou tout ``PlateRecognizer`` compatible)
* La liste exacte des plugin names dispatchables par étape

Objectif : **skip tout le bloc pipeline** quand une caméra n'a AUCUN plugin
activé qui correspond à une étape → zéro CPU/VRAM consommé.

Le registry maintient un cache invalidé sur changement de ``enabled_plugins``
(hash de la whitelist) ou sur reload plugin manager.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("pipeline_v2.registry")


# Plugins ANPR reconnus (les PlateRecognizers). Enrichir si de nouveaux
# moteurs OCR sont ajoutés au marketplace.
KNOWN_ANPR_PROVIDERS = {"fast-alpr", "paddle-ocr", "google-vision-anpr",
                        "openalpr", "azure-vision-anpr", "codeproject-ai-anpr"}


@dataclass
class CameraGraph:
    """Graphe d'exécution compilé pour UNE caméra.

    Chaque champ indique si l'étape correspondante doit être exécutée pour
    cette caméra, et la liste précise des plugin names à dispatcher.

    Si tous les booléens ``needs_*`` sont False, le pipeline downstream
    peut être **entièrement court-circuité** (aucune allocation, aucune
    tâche async, aucun compteur incrémenté).
    """
    camera_id: str
    enabled_plugins_hash: str = ""
    enabled_plugins: list[str] = field(default_factory=list)

    # Étapes actives ou non
    needs_detection: bool = False   # au moins un FrameAnalyzer activé
    needs_tracking: bool = False    # au moins un Tracker activé
    needs_segmentation: bool = False
    needs_business: bool = False    # au moins un PipelineConsumer activé
    needs_anpr: bool = False        # fast-alpr (ou autre PlateRecognizer) activé

    # Plugin names dispatchables par étape (respecte enabled_plugins + état bus)
    detectors: list[str] = field(default_factory=list)
    trackers: list[str] = field(default_factory=list)
    segmenters: list[str] = field(default_factory=list)
    consumers: list[str] = field(default_factory=list)
    recognizers: list[str] = field(default_factory=list)

    built_at: float = 0.0
    build_reason: str = "initial"

    @property
    def total_active_plugins(self) -> int:
        return (len(self.detectors) + len(self.trackers)
                + len(self.segmenters) + len(self.consumers)
                + len(self.recognizers))

    @property
    def is_empty(self) -> bool:
        """True si aucune étape n'a besoin de tourner → skip complet possible."""
        return not (self.needs_detection or self.needs_tracking
                    or self.needs_segmentation or self.needs_business
                    or self.needs_anpr)

    def to_dict(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "enabled_plugins": list(self.enabled_plugins),
            "enabled_plugins_hash": self.enabled_plugins_hash,
            "needs": {
                "detection": self.needs_detection,
                "tracking": self.needs_tracking,
                "segmentation": self.needs_segmentation,
                "business": self.needs_business,
                "anpr": self.needs_anpr,
            },
            "plugins": {
                "detectors": list(self.detectors),
                "trackers": list(self.trackers),
                "segmenters": list(self.segmenters),
                "consumers": list(self.consumers),
                "recognizers": list(self.recognizers),
            },
            "total_active_plugins": self.total_active_plugins,
            "is_empty": self.is_empty,
            "built_at": self.built_at,
            "build_reason": self.build_reason,
        }


class CameraGraphRegistry:
    """Cache des graphes d'exécution par caméra.

    Reconstruit lazily lorsque la whitelist ``enabled_plugins`` change
    (comparaison par hash). Peut être forcé à recompiler via ``invalidate()``
    (typiquement après reload plugin manager ou toggle d'un plugin global).
    """

    def __init__(self):
        self._graphs: dict[str, CameraGraph] = {}
        self._bus_version: int = 0   # incrémenté quand le bus change globalement

    def bump_bus_version(self) -> None:
        """Invalide tous les graphes (à appeler sur reload plugin manager)."""
        self._bus_version += 1
        # Ne détruit pas immédiatement — la prochaine get() re-vérifiera
        # le bus_version et reconstruira si nécessaire.

    def invalidate(self, camera_id: Optional[str] = None) -> None:
        if camera_id:
            self._graphs.pop(camera_id, None)
        else:
            self._graphs.clear()

    def get(self, camera_id: str, enabled_plugins: Optional[list[str]] = None,
            bus=None) -> CameraGraph:
        """Retourne le graphe compilé pour la caméra (rebuild si stale)."""
        enabled_plugins = list(enabled_plugins or [])
        h = _hash_plugins(enabled_plugins, self._bus_version)
        existing = self._graphs.get(camera_id)
        if existing and existing.enabled_plugins_hash == h:
            return existing
        graph = self._build(camera_id, enabled_plugins, bus,
                            reason="rebuild" if existing else "initial")
        graph.enabled_plugins_hash = h
        self._graphs[camera_id] = graph
        logger.info(
            "pipeline_v2.registry: %s graph rebuilt · detect=%s track=%s biz=%s anpr=%s (whitelist=%s)",
            camera_id, graph.needs_detection, graph.needs_tracking,
            graph.needs_business, graph.needs_anpr,
            "all" if not enabled_plugins else str(len(enabled_plugins)),
        )
        return graph

    def all_graphs(self) -> dict[str, dict]:
        return {cid: g.to_dict() for cid, g in self._graphs.items()}

    def stats(self) -> dict:
        empty = sum(1 for g in self._graphs.values() if g.is_empty)
        return {
            "cached_cameras": len(self._graphs),
            "cameras_with_empty_pipeline": empty,
            "cameras_with_active_pipeline": len(self._graphs) - empty,
            "bus_version": self._bus_version,
        }

    # ── Construction interne ────────────────────────────────────────

    def _build(self, camera_id: str, enabled_plugins: list[str],
               bus, reason: str) -> CameraGraph:
        graph = CameraGraph(
            camera_id=camera_id,
            enabled_plugins=list(enabled_plugins),
            built_at=time.time(),
            build_reason=reason,
        )
        if bus is None:
            # Sans bus, on ne peut rien décider — retourne un graphe "conservateur"
            # (dispatch legacy → tous les plugins actifs sont potentiellement
            # candidats, on n'a pas d'info pour restreindre).
            graph.needs_detection = True
            graph.needs_tracking = True
            graph.needs_business = True
            graph.needs_anpr = True
            return graph

        whitelist = set(enabled_plugins)
        use_whitelist = bool(whitelist)

        def _keep(entry) -> bool:
            if not entry.is_dispatchable():
                return False
            return (not use_whitelist) or (entry.name in whitelist)

        # 1) Détecteurs (FrameAnalyzer)
        for e in bus.active("FrameAnalyzer"):
            if _keep(e):
                graph.detectors.append(e.name)
        graph.needs_detection = bool(graph.detectors)

        # 2) Trackers
        for e in bus.active("Tracker"):
            if _keep(e):
                graph.trackers.append(e.name)
        graph.needs_tracking = bool(graph.trackers)

        # 3) Segmenters (opt-in coûteux)
        for e in bus.active("Segmenter"):
            if _keep(e):
                graph.segmenters.append(e.name)
        graph.needs_segmentation = bool(graph.segmenters)

        # 4) PipelineConsumer (business)
        for e in bus.active("PipelineConsumer"):
            if _keep(e):
                graph.consumers.append(e.name)
        graph.needs_business = bool(graph.consumers)

        # 5) PlateRecognizer — ANPR (whitelist plus permissive : accepte tout
        #    PlateRecognizer connu même s'il n'a pas d'entry sur le bus, car
        #    fast-alpr peut tourner directement dans ai_engine sans BusEntry).
        for e in bus.active("PlateRecognizer"):
            if _keep(e):
                graph.recognizers.append(e.name)
        # fast-alpr direct (dans ai_engine) → considéré actif si whitelist vide
        # ou si "fast-alpr" est dans la whitelist.
        direct_anpr_active = (not use_whitelist) or ("fast-alpr" in whitelist)
        graph.needs_anpr = bool(graph.recognizers) or direct_anpr_active

        return graph


def _hash_plugins(enabled_plugins: list[str], bus_version: int) -> str:
    """Hash déterministe pour détecter les changements de config."""
    if not enabled_plugins:
        payload = "*"
    else:
        payload = "|".join(sorted(str(p) for p in enabled_plugins))
    return f"{payload}#v{bus_version}"


# Singleton exposé au reste du backend
registry = CameraGraphRegistry()
