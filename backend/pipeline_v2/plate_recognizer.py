"""v0.5.6 Phase B suite · Abstraction PlateRecognizer (OCR core).

Le pipeline ne doit **jamais** dépendre directement de `fast-alpr`.
Cette interface expose un contrat unique auquel toute implémentation
(FastALPR, PaddleOCR, OpenALPR, EasyOCR, Tesseract, ANPR-EPS,
plate-recognizer cloud, moteurs custom) doit se conformer.

Le pipeline demande un ``PlateRecognizer`` au registry, lui passe le
crop véhicule et consomme une ``list[PlateOcrResult]`` — indépendante
du moteur d'origine. Ajouter PaddleOCR comme moteur core devient :

    plate_registry.register("paddle-ocr", PaddleOcrRecognizer)

sans toucher au pipeline. La sélection par caméra sera branchée en
Phase C via ``cam_config['pipeline_config']['anpr'][0]`` (moteur core).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class PlateOcrResult:
    """Lecture OCR normalisée, indépendante du moteur.

    * text : texte de la plaque (brut, non normalisé — normalisation faite
      par le layer fusion downstream).
    * confidence : score [0, 1].
    * bbox_in_roi : coordonnées de la plaque **relatives au crop véhicule**
      (x1, y1, x2, y2). Le pipeline convertira en absolu.
    """
    text: str
    confidence: float
    bbox_in_roi: tuple[float, float, float, float]


@runtime_checkable
class PlateRecognizer(Protocol):
    """Interface OCR minimale."""

    name: str  # « fast-alpr », « paddle-ocr », « openalpr »…

    def recognize(self, vehicle_crop_bgr) -> list[PlateOcrResult]:
        """OCR sur un crop véhicule BGR (numpy H×W×3, uint8).

        Retourne une liste triée par confidence décroissante. Ne lève
        pas d'exception : retourne [] et logue en cas d'erreur.
        """
        ...


class FastAlprRecognizer:
    """Wrapper autour du singleton ``ai_engine._alpr`` (fast-alpr).

    Le lock global ``ai_engine.ALPR_INFERENCE_LOCK`` (v0.5.6 P0-1) est
    acquis en interne — le pipeline n'a rien à sérialiser.
    """

    name = "fast-alpr"

    def recognize(self, vehicle_crop_bgr) -> list[PlateOcrResult]:
        import ai_engine as _ae
        if _ae._alpr is None or vehicle_crop_bgr is None:
            return []
        try:
            with _ae.ALPR_INFERENCE_LOCK:
                raw = list(_ae._alpr.predict(vehicle_crop_bgr))
        except Exception:
            return []
        out: list[PlateOcrResult] = []
        for r in raw:
            if not getattr(r, "ocr", None) or not r.ocr.text:
                continue
            bb = r.detection.bounding_box
            out.append(PlateOcrResult(
                text=str(r.ocr.text),
                confidence=float(r.ocr.confidence),
                bbox_in_roi=(float(bb.x1), float(bb.y1),
                              float(bb.x2), float(bb.y2)),
            ))
        out.sort(key=lambda r: r.confidence, reverse=True)
        return out


# ═════════════════════════════════════════════════════════════════════════
# Registry
# ═════════════════════════════════════════════════════════════════════════
class PlateRecognizerRegistry:
    """Registry des moteurs OCR core, même pattern que ``DetectorRegistry``.

    Le "moteur core" est celui qui produit la lecture principale sur les
    crops véhicules — dispatché depuis ``_stage_anpr``. Les moteurs
    **additionnels** (multi-ANPR) restent gérés par le plugin bus et
    fusionnés via ``_apply_hierarchical_anpr_fusion``.
    """

    def __init__(self) -> None:
        self._factories: dict[str, type] = {}
        self._instances: dict[str, PlateRecognizer] = {}
        self._default = "fast-alpr"

    def register(self, name: str, factory: type) -> None:
        self._factories[name] = factory

    def get(self, name: str) -> PlateRecognizer | None:
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

    def get_active(self, cam_config: dict | None = None) -> tuple[PlateRecognizer, str, str | None]:
        """Retourne (recognizer, name_effectif, warning_ou_None).

        v0.5.6 Phase C · lecture de la config par caméra :
          ``cam_config['pipeline_config']['anpr'][0]`` (moteur core) — les
          suivants sont dispatchés par le plugin bus (multi-OCR).
        """
        requested = self._default
        warning = None
        if cam_config:
            pc = (cam_config.get("pipeline_config") or {}) if isinstance(cam_config, dict) else {}
            anpr_list = pc.get("anpr") or []
            if isinstance(anpr_list, list) and anpr_list:
                wanted = anpr_list[0]
                if isinstance(wanted, str) and wanted:
                    if wanted in self._factories:
                        requested = wanted
                    else:
                        warning = (
                            f"OCR core '{wanted}' demandé par la caméra mais "
                            f"non enregistré (connus: {self.known()}). "
                            f"Fallback vers '{self._default}'."
                        )
        rec = self.get(requested)
        if rec is not None:
            return rec, requested, warning
        return _NULL_PLATE_RECOGNIZER, requested, (
            warning or f"OCR core '{requested}' introuvable dans le registry."
        )

    def known(self) -> list[str]:
        return sorted(self._factories.keys())


class _NullPlateRecognizer:
    """OCR no-op — retourne toujours une liste vide."""
    name = "null"
    def recognize(self, vehicle_crop_bgr) -> list[PlateOcrResult]:  # noqa: ARG002
        return []


_NULL_PLATE_RECOGNIZER = _NullPlateRecognizer()

# Instance globale — importée par le pipeline (`_stage_anpr`).
plate_registry = PlateRecognizerRegistry()
plate_registry.register("fast-alpr", FastAlprRecognizer)
