"""Pipeline v2 · ANPR Quality Evaluator + Auto-deactivation (v0.4.2 · P1/P2).

**Principe métier** (demande utilisateur v0.4.1) :
    "Pas de plaque > fausse plaque" — mieux vaut suspendre temporairement l'OCR
    plutôt que de générer des lectures erronées quand les conditions ne s'y
    prêtent pas (nuit, contre-jour, angle défavorable, capteur saturé...).

**Score qualité** (0.0 = mauvais, 1.0 = excellent) basé sur :
    - ``brightness_ok`` : luminosité moyenne dans une fenêtre acceptable (30-220)
    - ``sharpness_ok``  : variance du Laplacien >= seuil (image non-floue)
    - ``contrast_ok``   : écart-type des niveaux >= seuil (image non-plate)
    - ``is_night``      : la scène est-elle nocturne (heure + luminosité)

**Auto-désactivation** :
    Si ``score < threshold`` pendant N cycles consécutifs → l'OCR est
    automatiquement suspendu pour cette caméra. Une notification est
    remontée à l'UI ("ANPR suspendu automatiquement — conditions insuffisantes").
    L'OCR reprend automatiquement quand le score remonte au-dessus du seuil
    pendant M cycles.

**Caméras spécialisées** (P2 · Issue #5) :
    Certains modèles Dahua ITC (ITC413/ITC237/ITC215) et Hikvision DeepInView
    embarquent un IR dédié + optique/shutter/gain optimisés pour l'ANPR
    24/7. Ces caméras contournent l'auto-désactivation (l'OCR reste actif
    même en nuit noire).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger("pipeline_v2.anpr_quality")


# ─── Signatures de caméras ANPR spécialisées ──────────────────────────
# Ces caméras sont conçues nativement pour l'ANPR 24/7 et ne subissent
# pas l'auto-désactivation qualité (elles gèrent le bas éclairage
# elles-mêmes via IR / capteur global-shutter / triple-exposition).
SPECIALIZED_ANPR_MODELS = {
    # Dahua ITC (Intelligent Traffic Camera)
    "itc413": "Dahua ITC413 · ANPR 24/7 dédié",
    "itc237": "Dahua ITC237 · ANPR 24/7 dédié",
    "itc215": "Dahua ITC215 · ANPR 24/7 dédié",
    "itc352": "Dahua ITC352 · ANPR 24/7 dédié",
    # Hikvision DeepInView
    "ids-2cd7a": "Hikvision DeepInView · ANPR + LFR 24/7",
    "ids-2td81": "Hikvision DeepInView Series · ANPR 24/7",
    # Axis P/Q ANPR
    "p1465-le": "Axis P1465-LE · ANPR optimisé",
    # Bosch AutoDome IP starlight
    "autodome-ip-starlight": "Bosch AutoDome starlight · basse lumière",
}


@dataclass
class QualityScore:
    """Résultat de l'évaluation qualité pour UNE frame."""
    score: float                    # 0.0 - 1.0
    brightness: float = 0.0         # moyenne des pixels (0-255)
    sharpness: float = 0.0          # variance du Laplacien (>100 = net)
    contrast: float = 0.0           # écart-type des pixels
    is_night: bool = False
    reasons_pass: list[str] = field(default_factory=list)
    reasons_fail: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 3),
            "brightness": round(self.brightness, 1),
            "sharpness": round(self.sharpness, 1),
            "contrast": round(self.contrast, 1),
            "is_night": self.is_night,
            "reasons_pass": list(self.reasons_pass),
            "reasons_fail": list(self.reasons_fail),
        }


@dataclass
class AnprCameraState:
    """État runtime de l'ANPR pour une caméra (utilisé par le monitoring UI).

    Machine à états : ACTIVE ↔ SUSPENDED (via hystérésis N/M cycles).
    """
    camera_id: str
    suspended: bool = False
    last_score: float = 1.0
    last_evaluated_at: float = 0.0
    last_reason: str = ""
    consecutive_bad: int = 0        # nb cycles sous seuil
    consecutive_good: int = 0       # nb cycles au-dessus (pour resume)
    suspended_since: Optional[float] = None
    total_suspensions: int = 0
    is_specialized: bool = False    # ANPR 24/7 dédié → bypass auto-suspend
    specialized_model: str = ""

    def to_dict(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "suspended": self.suspended,
            "last_score": round(self.last_score, 3),
            "last_evaluated_at": self.last_evaluated_at,
            "last_reason": self.last_reason,
            "consecutive_bad": self.consecutive_bad,
            "consecutive_good": self.consecutive_good,
            "suspended_since": self.suspended_since,
            "total_suspensions": self.total_suspensions,
            "is_specialized": self.is_specialized,
            "specialized_model": self.specialized_model,
        }


class AnprQualityController:
    """Contrôleur central de la qualité ANPR + auto-suspension.

    Config (défauts calibrés sur scène urbaine standard) :
      - ``min_score``           : seuil sous lequel on considère la frame trop
                                   dégradée pour OCR (défaut 0.4)
      - ``suspend_after_bad``   : nb cycles consécutifs sous seuil avant
                                   suspension (défaut 5 · anti-blip)
      - ``resume_after_good``   : nb cycles consécutifs au-dessus du seuil
                                   avant reprise (défaut 3)
      - ``night_hour_start`` / ``night_hour_end`` : heure de nuit (défaut 22h→6h)
      - ``brightness_min/max``  : plage acceptable (30..220)
      - ``sharpness_min``       : variance Laplacien minimum (100)
      - ``contrast_min``        : écart-type minimum (25)

    Les caméras ``is_specialized`` (Dahua ITC / Hikvision DeepInView) ne
    subissent JAMAIS l'auto-suspension → OCR toujours actif.
    """

    def __init__(self,
                 min_score: float = 0.4,
                 suspend_after_bad: int = 5,
                 resume_after_good: int = 3,
                 brightness_min: float = 30,
                 brightness_max: float = 220,
                 sharpness_min: float = 100,
                 contrast_min: float = 25,
                 night_hour_start: int = 22,
                 night_hour_end: int = 6):
        self.min_score = float(min_score)
        self.suspend_after_bad = int(suspend_after_bad)
        self.resume_after_good = int(resume_after_good)
        self.brightness_min = float(brightness_min)
        self.brightness_max = float(brightness_max)
        self.sharpness_min = float(sharpness_min)
        self.contrast_min = float(contrast_min)
        self.night_hour_start = int(night_hour_start)
        self.night_hour_end = int(night_hour_end)

        self._states: dict[str, AnprCameraState] = {}

    def configure(self, **kw) -> None:
        for k in ("min_score", "suspend_after_bad", "resume_after_good",
                  "brightness_min", "brightness_max", "sharpness_min",
                  "contrast_min", "night_hour_start", "night_hour_end"):
            if k in kw and kw[k] is not None:
                setattr(self, k, type(getattr(self, k))(kw[k]))

    # ── Évaluation qualité d'une frame ────────────────────────────────

    def evaluate(self, img, now: Optional[datetime] = None) -> QualityScore:
        """Calcule le score qualité d'une frame numpy BGR.

        Aucun import numpy/cv2 au niveau module → chargé à la demande pour
        garder ce module utilisable dans les tests unitaires sans OpenCV.
        """
        import cv2
        import numpy as np
        now = now or datetime.now()

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean())
        contrast = float(gray.std())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        pass_reasons: list[str] = []
        fail_reasons: list[str] = []

        # Sous-scores 0.0 - 1.0 lissés
        def _clip(x: float, lo: float, hi: float) -> float:
            return max(0.0, min(1.0, (x - lo) / (hi - lo) if hi > lo else 0.0))

        # 1) Luminosité : idéal dans [80..180], acceptable [30..220]
        if self.brightness_min <= brightness <= self.brightness_max:
            b_score = 1.0 - abs(brightness - 130) / 100  # 1.0 à 130, 0.5 aux bords
            b_score = max(0.5, min(1.0, b_score))
            pass_reasons.append(f"brightness={brightness:.0f}")
        else:
            b_score = _clip(brightness, self.brightness_min * 0.5,
                            self.brightness_min) if brightness < self.brightness_min else \
                      _clip(self.brightness_max + 30 - brightness, 0, 30)
            fail_reasons.append(
                f"brightness={brightness:.0f} hors [{self.brightness_min:.0f}..{self.brightness_max:.0f}]"
            )

        # 2) Netteté (Laplacian variance)
        s_score = _clip(sharpness, self.sharpness_min * 0.5, self.sharpness_min * 3)
        if sharpness >= self.sharpness_min:
            pass_reasons.append(f"sharpness={sharpness:.0f}")
        else:
            fail_reasons.append(f"sharpness={sharpness:.0f} < {self.sharpness_min:.0f} (flou)")

        # 3) Contraste
        c_score = _clip(contrast, self.contrast_min * 0.5, self.contrast_min * 2)
        if contrast >= self.contrast_min:
            pass_reasons.append(f"contrast={contrast:.0f}")
        else:
            fail_reasons.append(f"contrast={contrast:.0f} < {self.contrast_min:.0f} (plat)")

        # 4) Heure de nuit (heuristique — sans capteur photométrique)
        h = now.hour
        if self.night_hour_start >= self.night_hour_end:
            is_night = h >= self.night_hour_start or h < self.night_hour_end
        else:
            is_night = self.night_hour_start <= h < self.night_hour_end

        # Score global (moyenne pondérée : netteté domine — c'est ce qui
        # tue le plus l'OCR).
        score = 0.45 * s_score + 0.30 * b_score + 0.25 * c_score

        return QualityScore(
            score=round(score, 3),
            brightness=round(brightness, 1),
            sharpness=round(sharpness, 1),
            contrast=round(contrast, 1),
            is_night=is_night,
            reasons_pass=pass_reasons,
            reasons_fail=fail_reasons,
        )

    # ── Décision auto-suspension / reprise ────────────────────────────

    def should_run_anpr(self, camera_id: str, img,
                        camera: Optional[dict] = None,
                        now: Optional[datetime] = None) -> tuple[bool, AnprCameraState, QualityScore]:
        """Retourne ``(should_run, state, quality)``.

        ``camera`` doit contenir au minimum ``id``, ``model`` (str) pour
        activer le mode ``is_specialized``.
        """
        now = now or datetime.now()
        cam_model = ((camera or {}).get("model") or "").lower()

        state = self._states.setdefault(camera_id, AnprCameraState(camera_id=camera_id))

        # Détecte caméra spécialisée (bypass auto-suspend)
        is_specialized = False
        specialized_model = ""
        for signature, label in SPECIALIZED_ANPR_MODELS.items():
            if signature in cam_model:
                is_specialized = True
                specialized_model = label
                break
        state.is_specialized = is_specialized
        state.specialized_model = specialized_model

        quality = self.evaluate(img, now=now)
        state.last_score = quality.score
        state.last_evaluated_at = time.time()

        # Caméra spécialisée → toujours actif, quel que soit le score
        if is_specialized:
            state.suspended = False
            state.consecutive_bad = 0
            state.consecutive_good = 0
            state.last_reason = f"specialized · {specialized_model}"
            return True, state, quality

        # Machine à états avec hystérésis N/M
        under_threshold = quality.score < self.min_score
        if under_threshold:
            state.consecutive_bad += 1
            state.consecutive_good = 0
            if not state.suspended and state.consecutive_bad >= self.suspend_after_bad:
                state.suspended = True
                state.suspended_since = time.time()
                state.total_suspensions += 1
                reasons = "; ".join(quality.reasons_fail) or "score insuffisant"
                state.last_reason = f"ANPR suspendu automatiquement — {reasons}"
                logger.warning(
                    "anpr_quality.suspend camera=%s score=%.2f reasons=%s",
                    camera_id, quality.score, reasons,
                )
        else:
            state.consecutive_good += 1
            state.consecutive_bad = 0
            if state.suspended and state.consecutive_good >= self.resume_after_good:
                state.suspended = False
                state.suspended_since = None
                state.last_reason = f"ANPR repris — conditions redevenues favorables (score={quality.score:.2f})"
                logger.info(
                    "anpr_quality.resume camera=%s score=%.2f",
                    camera_id, quality.score,
                )
            elif not state.suspended:
                state.last_reason = f"score={quality.score:.2f} OK"

        should_run = not state.suspended
        return should_run, state, quality

    # ── Introspection (pour l'UI Diagnostics) ─────────────────────────

    def states(self) -> dict[str, dict]:
        return {cid: s.to_dict() for cid, s in self._states.items()}

    def state(self, camera_id: str) -> Optional[dict]:
        s = self._states.get(camera_id)
        return s.to_dict() if s else None

    def reset(self, camera_id: Optional[str] = None) -> None:
        if camera_id:
            self._states.pop(camera_id, None)
        else:
            self._states.clear()

    def config_dict(self) -> dict:
        return {
            "min_score": self.min_score,
            "suspend_after_bad": self.suspend_after_bad,
            "resume_after_good": self.resume_after_good,
            "brightness_min": self.brightness_min,
            "brightness_max": self.brightness_max,
            "sharpness_min": self.sharpness_min,
            "contrast_min": self.contrast_min,
            "night_hour_start": self.night_hour_start,
            "night_hour_end": self.night_hour_end,
        }


# Singleton runtime
anpr_quality = AnprQualityController()
