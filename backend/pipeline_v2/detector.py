"""v0.5.6 P0-2 · Abstraction Detector.

Le pipeline ne doit **jamais** dépendre directement d'Ultralytics. Cette
interface expose un contrat unique auquel toute implémentation
(YOLO, RT-DETR, RF-DETR, TensorRT, OpenVINO, ONNX, modèles custom) doit
se conformer.

Contrat minimal :

    class Detector(Protocol):
        name: str

        def detect(self, frame_bgr) -> list[DetectionObject]:
            '''Retourne les détections d'une frame BGR (numpy array).'''

À ce stade (Phase A), un seul détecteur est effectivement branché :
:class:`YoloDetector` qui wrappe ``ai_engine._model``. Les stubs
RT-DETR / RF-DETR / OpenVINO / ONNX / YOLO-NAS continuent de retourner
des listes vides — leur intégration réelle est prévue en Phase B.

Cette couche prépare le passage vers un ``PipelineFactory`` où chaque
caméra pourra choisir son détecteur via ``pipeline_config.detector``
sans modifier une seule ligne du code métier (voir Phase C).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class DetectionObject:
    """Objet détecté normalisé, indépendant du moteur d'inférence.

    Champs :
      * bbox : (x1, y1, x2, y2) en pixels absolus de la frame source.
      * label : nom sémantique (« person », « car », « truck »…).
        JAMAIS un ID de classe COCO — les plugins métier ne connaissent
        pas les modèles.
      * confidence : score normalisé dans [0, 1].
      * class_id : identifiant natif du modèle (optionnel, purement
        informatif — ne pas s'en servir dans les plugins).
      * track_id : rempli plus tard par le stage Tracking (None ici).
      * metadata : extensions moteur-spécifiques (ex : masks, keypoints).
    """
    bbox: tuple[float, float, float, float]
    label: str
    confidence: float
    class_id: int | None = None
    track_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Detector(Protocol):
    """Interface minimale à laquelle tout détecteur doit se conformer."""

    name: str  # « yolov11 », « rt-detr », « tensorrt »…

    def detect(self, frame_bgr) -> list[DetectionObject]:
        """Inférence sur une frame BGR (numpy H×W×3, uint8).

        Doit retourner une liste **triée par confidence décroissante**
        d'objets détectés. Ne lève pas d'exception en cas d'échec :
        retourne une liste vide et logue l'erreur.
        """
        ...


class YoloDetector:
    """Wrapper Detector autour du singleton YOLO d'``ai_engine``.

    Cette classe ne recharge PAS le modèle : elle réutilise
    ``ai_engine._model`` déjà initialisé. Le lock de sérialisation
    (``ai_engine.YOLO_INFERENCE_LOCK``, v0.5.6 P0-1) est appliqué en
    interne pour éviter la corruption sous concurrence.

    Utilisé aujourd'hui uniquement par tests / documentation — le
    pipeline live continue d'appeler directement ``_ae._model.predict``
    (avec le lock) pour ne pas introduire de régression de perf. La
    migration complète est prévue en Phase B.
    """

    name = "yolov11"

    def detect(self, frame_bgr) -> list[DetectionObject]:
        import ai_engine as _ae
        if _ae._model is None or frame_bgr is None:
            return []
        try:
            with _ae.YOLO_INFERENCE_LOCK:
                results = _ae._model.predict(
                    frame_bgr,
                    conf=_ae._cfg("confidence", _ae.AI_CONFIDENCE),
                    device=_ae._detected_device(),
                    verbose=False,
                )[0]
        except Exception:
            return []
        return _yolo_results_to_objects(results, _ae)


def _yolo_results_to_objects(results, _ae) -> list[DetectionObject]:
    """Convertit une sortie Ultralytics en :class:`DetectionObject`.

    Cette conversion n'est pas performance-critique : les plugins qui
    utilisent l'interface ``Detector`` sont hors du chemin critique
    (le pipeline live utilise encore les tenseurs bruts).
    """
    if results is None or not hasattr(results, "boxes") or results.boxes is None:
        return []
    names = getattr(results, "names", {}) or {}
    out: list[DetectionObject] = []
    for box in results.boxes:
        try:
            xyxy = box.xyxy[0].tolist()
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            label = names.get(cls_id, str(cls_id))
            out.append(DetectionObject(
                bbox=(float(xyxy[0]), float(xyxy[1]),
                       float(xyxy[2]), float(xyxy[3])),
                label=label,
                confidence=conf,
                class_id=cls_id,
            ))
        except Exception:  # pragma: no cover
            continue
    out.sort(key=lambda o: o.confidence, reverse=True)
    return out


# ═════════════════════════════════════════════════════════════════════════
# DetectorRegistry — v0.5.6 Phase B
# ═════════════════════════════════════════════════════════════════════════
class DetectorRegistry:
    """Registry singleton des détecteurs disponibles à l'exécution.

    Pattern factory : les implémentations concrètes (`YoloDetector`,
    `RTDetrDetector`, `TensorRTDetector`…) s'enregistrent au chargement
    et le pipeline demande une instance par nom :

        registry.register("yolov11", YoloDetector)
        registry.register("rt-detr", RTDetrDetector)
        det = registry.get("yolov11")        # instance singleton
        objs = det.detect(frame_bgr)

    - ``get_active(cam_config)`` retourne le détecteur choisi pour cette
      caméra. Aujourd'hui (Phase B), seule la config globale est lue —
      la config par-caméra sera branchée en Phase C.
    - Si le détecteur demandé n'existe pas → fallback vers ``yolov11``
      avec un ``warning`` explicite (jamais silencieux).
    """

    def __init__(self) -> None:
        self._factories: dict[str, type] = {}
        self._instances: dict[str, Detector] = {}
        self._default = "yolov11"

    def register(self, name: str, factory: type) -> None:
        self._factories[name] = factory

    def get(self, name: str) -> Detector | None:
        if name in self._instances:
            return self._instances[name]
        factory = self._factories.get(name)
        if factory is None:
            return None
        try:
            inst = factory()
            self._instances[name] = inst
            return inst
        except Exception:  # pragma: no cover
            return None

    def get_active(self, cam_config: dict | None = None) -> tuple[Detector, str, str | None]:
        """Retourne (detector_actif, name_effectif, warning_ou_None).

        v0.5.6 Phase C · lecture de la config par caméra :
          ``cam_config['pipeline_config']['detector']``. Si absent →
          détecteur par défaut (yolov11) sans warning. Si présent mais
          non enregistré → fallback vers le default AVEC warning explicite.
        """
        requested = self._default
        warning = None
        if cam_config:
            pc = (cam_config.get("pipeline_config") or {}) if isinstance(cam_config, dict) else {}
            wanted = pc.get("detector")
            if isinstance(wanted, str) and wanted:
                if wanted in self._factories:
                    requested = wanted
                else:
                    warning = (
                        f"Détecteur '{wanted}' demandé par la caméra mais non "
                        f"enregistré (connus: {self.known()}). Fallback vers "
                        f"'{self._default}'."
                    )
        det = self.get(requested)
        if det is not None:
            return det, requested, warning
        return _NULL_DETECTOR, requested, (
            warning or f"Détecteur '{requested}' introuvable dans le registry."
        )

    def known(self) -> list[str]:
        return sorted(self._factories.keys())


class _NullDetector:
    """Détecteur no-op — retourne toujours zéro détection.

    Utilisé si le YOLO n'est pas encore chargé (démarrage) ou si le
    modèle demandé n'a pas pu être instancié. **Ne jamais crash** : le
    pipeline continue silencieusement à zéro détection, comme si aucune
    caméra n'avait de contenu intéressant à cet instant.
    """
    name = "null"

    def detect(self, frame_bgr) -> list[DetectionObject]:  # noqa: ARG002
        return []


_NULL_DETECTOR = _NullDetector()

# Instance globale — importée par le pipeline (`_stage_detection`).
registry = DetectorRegistry()
registry.register("yolov11", YoloDetector)
