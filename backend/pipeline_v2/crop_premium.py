"""Pipeline v2 · Crop Premium v2 — recrop automatique + fallbacks image processing.

Mandat v0.8-rc5 (FEATURE FREEZE · Stabilisation Sprint 2 · Priorité #2 absolue) :

    Quand le crop plaque a un `score_100 < 60` (assess_crop_quality),
    on ne l'accepte PAS : on tente automatiquement plusieurs variantes
    (marges +5 % à +25 % + variantes de prétraitement) et on garde
    UNIQUEMENT le crop avec le meilleur score composite.

Le Multi-OCR ne doit recevoir que le meilleur crop possible.
Aucun OCR n'est déclenché ici — cette étape ne fait que produire un
crop optimal. L'OCR reste piloté par `camera_worker._stage_anpr`.

Approche cascade :

    1. Génération de 6 crops par marge (0, +5, +10, +15, +20, +25 %)
       sur ``image_hd`` (jamais preview MJPEG).
    2. Sur chaque crop → assess_crop_quality → ``score_100``.
    3. Sélection du top-K (K=3 par défaut) via score composite.
    4. Sur chaque top-K → application de N prétraitements :
         a) enhance_plate_crop (deskew + CLAHE + unsharp — déjà existant)
         b) denoise (fastNlMeansDenoising)
         c) perspective_correct (via minAreaRect si contours détectés)
       et on re-mesure la qualité de chaque résultat.
    5. Retourne (best_crop, best_quality, tried_count, method_used).

Tout est CPU-only (OpenCV) — pas de dépendance externe supplémentaire.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from .plate_quality import (
    CropQuality, assess_crop_quality, enhance_plate_crop,
)

logger = logging.getLogger("pipeline_v2.crop_premium")


# ═════════════════════════════════════════════════════════════════════
# Paramètres (surchargeables via API si besoin plus tard)
# ═════════════════════════════════════════════════════════════════════
DEFAULT_MARGINS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25)
DEFAULT_TOPK = 3
DEFAULT_MIN_ACCEPTABLE_SCORE = 60   # seuil déclencheur (score_100)
MAX_METHODS_PER_CROP = 4            # cap sécurité perf


@dataclass
class CropVariant:
    """Une variante testée (crop + prétraitement) et sa qualité mesurée."""
    crop: np.ndarray
    quality: CropQuality
    margin: float
    method: str                     # 'raw' | 'enhance' | 'denoise' | 'perspective'
    score_100: int

    def to_dict(self) -> dict:
        return {
            "margin": round(self.margin, 2),
            "method": self.method,
            "score_100": self.score_100,
            "width": self.quality.width,
            "height": self.quality.height,
        }


@dataclass
class CropPremiumResult:
    """Résultat final du run Crop Premium v2."""
    best_crop: np.ndarray
    best_quality: CropQuality
    best_method: str
    best_margin: float
    tried_count: int
    escalated: bool                 # True si score initial < seuil
    all_variants: list              # list[dict] pour debug/telemetry
    took_ms: float

    def to_dict(self) -> dict:
        return {
            "best_method": self.best_method,
            "best_margin": round(self.best_margin, 2),
            "best_score_100": self.best_quality.score_100,
            "best_size": f"{self.best_quality.width}x{self.best_quality.height}",
            "tried_count": self.tried_count,
            "escalated": self.escalated,
            "variants": self.all_variants,
            "took_ms": round(self.took_ms, 1),
        }


# ═════════════════════════════════════════════════════════════════════
# Point d'entrée principal
# ═════════════════════════════════════════════════════════════════════
def run_crop_premium(
    image_hd: np.ndarray,
    bbox: tuple,             # (x1, y1, x2, y2) absolu dans image_hd
    min_score: int = DEFAULT_MIN_ACCEPTABLE_SCORE,
    margins: tuple = DEFAULT_MARGINS,
    topk: int = DEFAULT_TOPK,
) -> CropPremiumResult:
    """Génère le crop plaque optimal via cascade multi-variants.

    Étapes :
      1. Crop initial (margin=0) → si score >= ``min_score`` → return direct.
      2. Sinon on escalade : génère toutes les marges, pick top-K, applique
         chaque méthode de prétraitement, retourne le meilleur global.

    Args:
        image_hd : image source HD (jamais preview / MJPEG).
        bbox : (x1, y1, x2, y2) absolus dans image_hd.
        min_score : seuil score_100 au-dessus duquel on ne dépense pas de
                    ressources (défaut 60).
        margins : marges à tester (relatives, 0.0 = pas de marge).
        topk : nombre de crops (parmi les marges) sur lesquels appliquer les
               prétraitements.

    Returns:
        CropPremiumResult avec best_crop garanti non-vide.
    """
    t0 = time.monotonic()
    x1, y1, x2, y2 = _sanitize_bbox(bbox, image_hd.shape)
    raw = image_hd[y1:y2, x1:x2]
    baseline_q = assess_crop_quality(raw)
    all_variants: list[CropVariant] = [CropVariant(
        crop=raw, quality=baseline_q, margin=0.0,
        method="raw", score_100=baseline_q.score_100,
    )]

    # Fast path : le crop initial est déjà de bonne qualité → return
    escalated = False
    if baseline_q.score_100 >= min_score or baseline_q.skip:
        return _finalize(all_variants, escalated=False, t0=t0)

    escalated = True
    # 1. Génération des variantes de marge
    for m in margins:
        if m == 0.0:
            continue  # déjà fait
        try:
            cropped = _crop_with_margin(image_hd, bbox, m)
            if cropped is None or cropped.size == 0:
                continue
            q = assess_crop_quality(cropped)
            all_variants.append(CropVariant(
                crop=cropped, quality=q, margin=m,
                method="raw", score_100=q.score_100,
            ))
        except Exception:
            logger.debug("crop margin %.2f a échoué (non bloquant)", m, exc_info=True)

    # 2. Sélection top-K variantes (par score) — évite d'appliquer 4 méthodes
    #    sur 6 crops = 24 opérations coûteuses. On garde top-K seulement.
    all_variants.sort(key=lambda v: v.score_100, reverse=True)
    top_candidates = [v for v in all_variants if not v.quality.skip][:topk]

    # 3. Application des prétraitements sur chaque top-K
    for base in list(top_candidates):
        # méthode a : enhance existante (deskew + CLAHE + sharpen)
        try:
            forced_q = _force_should_enhance(base.quality)
            enhanced = enhance_plate_crop(base.crop, forced_q)
            if enhanced is not None and enhanced.size:
                eq = assess_crop_quality(enhanced)
                all_variants.append(CropVariant(
                    crop=enhanced, quality=eq, margin=base.margin,
                    method="enhance", score_100=eq.score_100,
                ))
        except Exception:
            logger.debug("enhance a échoué", exc_info=True)

        # méthode b : denoise
        try:
            denoised = _denoise(base.crop)
            if denoised is not None and denoised.size:
                dq = assess_crop_quality(denoised)
                all_variants.append(CropVariant(
                    crop=denoised, quality=dq, margin=base.margin,
                    method="denoise", score_100=dq.score_100,
                ))
        except Exception:
            logger.debug("denoise a échoué", exc_info=True)

        # méthode c : perspective correction (si contour rectangulaire détecté)
        try:
            warped = _perspective_correct(base.crop)
            if warped is not None and warped.size:
                pq = assess_crop_quality(warped)
                all_variants.append(CropVariant(
                    crop=warped, quality=pq, margin=base.margin,
                    method="perspective", score_100=pq.score_100,
                ))
        except Exception:
            logger.debug("perspective a échoué", exc_info=True)

    return _finalize(all_variants, escalated=escalated, t0=t0)


# ═════════════════════════════════════════════════════════════════════
# Helpers internes
# ═════════════════════════════════════════════════════════════════════
def _finalize(variants: list[CropVariant], escalated: bool, t0: float) -> CropPremiumResult:
    """Trie et retourne le meilleur variant."""
    variants.sort(key=lambda v: v.score_100, reverse=True)
    best = variants[0]
    took = (time.monotonic() - t0) * 1000
    return CropPremiumResult(
        best_crop=best.crop, best_quality=best.quality,
        best_method=best.method, best_margin=best.margin,
        tried_count=len(variants), escalated=escalated,
        all_variants=[v.to_dict() for v in variants],
        took_ms=took,
    )


def _sanitize_bbox(bbox: tuple, shape: tuple) -> tuple:
    """Borne bbox aux dimensions de l'image (protection off-by-one)."""
    H, W = shape[:2]
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(int(x1), W - 1))
    y1 = max(0, min(int(y1), H - 1))
    x2 = max(x1 + 1, min(int(x2), W))
    y2 = max(y1 + 1, min(int(y2), H))
    return x1, y1, x2, y2


def _crop_with_margin(image_hd: np.ndarray, bbox: tuple, margin: float) -> Optional[np.ndarray]:
    """Étend la bbox d'une marge relative et re-crop.

    margin=0.10 → +10 % de la largeur/hauteur autour de la plaque.
    """
    H, W = image_hd.shape[:2]
    x1, y1, x2, y2 = bbox
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    dx = int(round(bw * margin))
    dy = int(round(bh * margin))
    nx1 = max(0, x1 - dx)
    ny1 = max(0, y1 - dy)
    nx2 = min(W, x2 + dx)
    ny2 = min(H, y2 + dy)
    if nx2 <= nx1 or ny2 <= ny1:
        return None
    return image_hd[ny1:ny2, nx1:nx2]


def _force_should_enhance(q: CropQuality) -> CropQuality:
    """Renvoie une copie du CropQuality avec ``should_enhance=True``.

    ``enhance_plate_crop`` no-op si ``should_enhance=False`` ; ce helper
    force l'activation pour les cas où le baseline est jugé "ok" par le
    filtre par défaut mais qu'on tente quand même l'enhancement en fallback.
    """
    from dataclasses import replace
    return replace(q, should_enhance=True, skip=False)


def _denoise(crop: np.ndarray) -> np.ndarray:
    """Denoise léger via fastNlMeansDenoising (color / gray auto)."""
    if crop.ndim == 3:
        return cv2.fastNlMeansDenoisingColored(crop, None, 7, 7, 7, 21)
    return cv2.fastNlMeansDenoising(crop, None, 7, 7, 21)


def _perspective_correct(crop: np.ndarray) -> Optional[np.ndarray]:
    """Tente une correction de perspective en détectant un quadrilatère.

    Cherche un contour rectangulaire (approxPolyDP 4 sommets) dans le crop
    et applique un warp perspective si trouvé. Retourne None si aucun
    quadrilatère plausible.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop.copy()
    # Threshold adaptatif (résistant aux variations d'éclairage)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    # Plus grand contour
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:3]
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(approx) > 0.4 * (crop.shape[0] * crop.shape[1]):
            # 4 sommets couvrant >40 % du crop → candidat plaque
            pts = approx.reshape(4, 2).astype(np.float32)
            # Ordre : top-left, top-right, bottom-right, bottom-left
            pts = _order_quad(pts)
            (tl, tr, br, bl) = pts
            wA = np.linalg.norm(br - bl)
            wB = np.linalg.norm(tr - tl)
            hA = np.linalg.norm(tr - br)
            hB = np.linalg.norm(tl - bl)
            W = max(int(wA), int(wB))
            H = max(int(hA), int(hB))
            if W < 30 or H < 15:  # trop petit — pas fiable
                continue
            dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype=np.float32)
            M = cv2.getPerspectiveTransform(pts, dst)
            return cv2.warpPerspective(crop, M, (W, H), flags=cv2.INTER_CUBIC)
    return None


def _order_quad(pts: np.ndarray) -> np.ndarray:
    """Ordonne 4 points en TL, TR, BR, BL (repère image)."""
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.stack([tl, tr, br, bl])
