"""Pipeline v2 · Plate Quality — évaluation qualité + amélioration crop plaque.

Objectif Wave C (v0.7.e) :
    Le crop DOIT toujours être optimal AVANT d'appeler l'OCR.
    Cette étape doit :
      1. Ne JAMAIS opérer sur le preview MJPEG ou sur une image redimensionnée
         (l'appelant garantit un crop HD extrait de ``ctx.image``).
      2. Évaluer la qualité (taille, netteté, contraste, inclinaison).
      3. Si crop « acceptable » → renvoyer tel quel.
      4. Si crop « améliorable » → appliquer deskew + contraste adaptatif
         (CLAHE) + un sharpen léger.
      5. Si crop « trop dégradé » → renvoyer un flag ``skip=True``.

Aucune modification de l'image originale : les enhancements travaillent
sur une copie du crop.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("pipeline_v2.plate_quality")


# Seuils par défaut (surchargeables via camera.plate_quality_config si besoin)
MIN_PLATE_SIDE_PX = 40          # côté minimum accepté (déjà filtré ailleurs mais garde)
MIN_SHARPNESS = 15.0            # variance du Laplacien — sous ce seuil on considère flou
MIN_CONTRAST = 20.0             # écart-type des niveaux de gris
MAX_SKEW_DEG = 15.0             # au delà : deskew agressif
GOOD_ENOUGH_SHARPNESS = 60.0    # au dessus : pas besoin d'améliorer
GOOD_ENOUGH_CONTRAST = 45.0     # idem


@dataclass
class CropQuality:
    """Rapport de qualité d'un crop plaque."""
    width: int
    height: int
    sharpness: float            # variance Laplacien
    contrast: float             # std niveaux de gris
    skew_deg: float             # angle estimé (0 si non détecté)
    score: float                # composite 0..1
    should_enhance: bool        # True si des améliorations utiles sont possibles
    skip: bool                  # True si crop inutilisable
    reason: str

    def to_dict(self) -> dict:
        return {
            "width": self.width, "height": self.height,
            "sharpness": round(self.sharpness, 1),
            "contrast": round(self.contrast, 1),
            "skew_deg": round(self.skew_deg, 1),
            "score": round(self.score, 2),
            "score_100": self.score_100,   # v0.7.h · Axe QoS · OCR Quality Score 0-100
            "should_enhance": self.should_enhance,
            "skip": self.skip,
            "reason": self.reason,
        }

    @property
    def score_100(self) -> int:
        """OCR Quality Score sur 0-100 (facile à lire dans l'UI)."""
        return int(round(self.score * 100))


def crop_hash(crop: np.ndarray, downsize: int = 16) -> str:
    """Hash perceptuel léger (aHash 16×16) pour cache de re-OCR.

    Un crop nettement différent produira un hash différent — les crops
    voisins d'un même véhicule stationné produiront le même hash → cache hit.
    """
    if crop is None or crop.size == 0:
        return "empty"
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    small = cv2.resize(gray, (downsize, downsize), interpolation=cv2.INTER_AREA)
    avg = small.mean()
    bits = (small > avg).astype(np.uint8).flatten()
    packed = np.packbits(bits).tobytes()
    return hashlib.blake2b(packed, digest_size=8).hexdigest()


def assess_crop_quality(crop: np.ndarray,
                         min_side: int = MIN_PLATE_SIDE_PX) -> CropQuality:
    """Évalue la qualité d'un crop plaque. Aucune modification de l'entrée."""
    if crop is None or crop.size == 0:
        return CropQuality(0, 0, 0.0, 0.0, 0.0, 0.0, False, True, "empty crop")
    h, w = crop.shape[:2]
    if w < min_side or h < min_side:
        return CropQuality(w, h, 0.0, 0.0, 0.0, 0.0, False, True,
                           f"trop petit ({w}x{h} < {min_side})")

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    # Sharpness (variance du Laplacien) : plus grand = plus net
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    sharpness = float(lap.var())
    # Contraste : écart-type des niveaux de gris
    contrast = float(gray.std())
    # Skew : détection via moments (approximation légère)
    skew = _estimate_skew_deg(gray)

    # Score composite pondéré (borne 0..1)
    sc_sharp = min(sharpness / GOOD_ENOUGH_SHARPNESS, 1.0)
    sc_contrast = min(contrast / GOOD_ENOUGH_CONTRAST, 1.0)
    sc_skew = max(0.0, 1.0 - abs(skew) / MAX_SKEW_DEG)
    score = 0.5 * sc_sharp + 0.3 * sc_contrast + 0.2 * sc_skew

    # Décisions
    skip = False
    should_enhance = False
    reason = "ok"
    if sharpness < MIN_SHARPNESS and contrast < MIN_CONTRAST:
        skip = True
        reason = f"crop trop dégradé (sharp={sharpness:.1f}, contrast={contrast:.1f})"
    elif sharpness < GOOD_ENOUGH_SHARPNESS or contrast < GOOD_ENOUGH_CONTRAST \
            or abs(skew) > 2.0:
        should_enhance = True
        reason = "améliorations utiles (sharp/contrast/skew)"

    return CropQuality(w, h, sharpness, contrast, skew, score,
                        should_enhance, skip, reason)


def enhance_plate_crop(crop: np.ndarray, quality: CropQuality) -> np.ndarray:
    """Applique deskew + CLAHE + sharpen léger si utile. Copie de sécurité.

    Retourne le crop amélioré. L'original n'est jamais modifié.
    """
    if quality.skip or not quality.should_enhance:
        return crop
    out = crop.copy()

    # 1) Deskew (uniquement si angle significatif)
    if abs(quality.skew_deg) > 2.0 and abs(quality.skew_deg) < 30.0:
        out = _deskew(out, quality.skew_deg)

    # 2) CLAHE sur canal L de LAB — améliore contraste local sans écraser
    #    les zones sur-exposées comme le ferait un stretch global.
    if quality.contrast < GOOD_ENOUGH_CONTRAST:
        if out.ndim == 3:
            lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            l2 = clahe.apply(l)
            out = cv2.cvtColor(cv2.merge((l2, a, b)), cv2.COLOR_LAB2BGR)
        else:
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            out = clahe.apply(out)

    # 3) Sharpen LÉGER (unsharp mask) — booste les contours OCR
    if quality.sharpness < GOOD_ENOUGH_SHARPNESS:
        blur = cv2.GaussianBlur(out, (0, 0), sigmaX=1.0)
        out = cv2.addWeighted(out, 1.5, blur, -0.5, 0)

    return out


def _estimate_skew_deg(gray: np.ndarray) -> float:
    """Estimation légère de l'angle d'inclinaison d'une plaque via Hough."""
    try:
        edges = cv2.Canny(gray, 60, 180, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=30,
                                 minLineLength=max(20, gray.shape[1] // 3),
                                 maxLineGap=10)
        if lines is None or len(lines) == 0:
            return 0.0
        angles = []
        for x1, y1, x2, y2 in lines[:, 0]:
            dx = x2 - x1
            dy = y2 - y1
            if dx == 0:
                continue
            ang = np.degrees(np.arctan2(dy, dx))
            # Ne garder que les lignes ~horizontales (typique du bord plaque)
            if -30 < ang < 30:
                angles.append(ang)
        if not angles:
            return 0.0
        return float(np.median(angles))
    except Exception:
        return 0.0


def _deskew(img: np.ndarray, angle_deg: float) -> np.ndarray:
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle_deg, 1.0)
    return cv2.warpAffine(img, M, (w, h),
                           flags=cv2.INTER_CUBIC,
                           borderMode=cv2.BORDER_REPLICATE)


# ═════════════════════════════════════════════════════════════════════
# Debug mode — sauvegarde images intermédiaires si MGVMS_DEBUG_OCR=1
# ═════════════════════════════════════════════════════════════════════
import os
from datetime import datetime

_DEBUG_ENABLED = os.environ.get("MGVMS_DEBUG_OCR", "0") in ("1", "true", "yes")
_DEBUG_DIR = os.environ.get("MGVMS_DEBUG_OCR_DIR", "/tmp/mgvms_debug_ocr")

# Aussi disponible via API PUT — permet d'activer sans redémarrer
_debug_runtime_override: Optional[bool] = None


def debug_enabled() -> bool:
    if _debug_runtime_override is not None:
        return _debug_runtime_override
    return _DEBUG_ENABLED


def set_debug_enabled(enabled: bool) -> None:
    global _debug_runtime_override
    _debug_runtime_override = bool(enabled)
    if enabled:
        os.makedirs(_DEBUG_DIR, exist_ok=True)
    logger.info("plate_quality.debug mode → %s (%s)", enabled, _DEBUG_DIR)


def save_debug_bundle(camera_id: str, track_id: Optional[int],
                       original_frame: np.ndarray,
                       vehicle_crop: np.ndarray,
                       raw_plate_crop: np.ndarray,
                       enhanced_plate_crop: Optional[np.ndarray],
                       quality: CropQuality,
                       ocr_results_by_engine: dict,
                       final_decision: dict) -> Optional[str]:
    """Sauvegarde un « bundle debug » complet quand `debug_enabled()`.

    Le bundle contient :
      * frame_full.jpg — image complète HD
      * vehicle.jpg — ROI véhicule
      * plate_raw.jpg — crop plaque brut
      * plate_enhanced.jpg — après deskew/CLAHE/sharpen (si utilisé)
      * bundle.json — quality + résultats de chaque OCR + décision finale

    Retourne le chemin du dossier créé, ou None si debug désactivé.
    """
    if not debug_enabled():
        return None
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        bundle_dir = os.path.join(_DEBUG_DIR, f"{camera_id}_{track_id or 'na'}_{ts}")
        os.makedirs(bundle_dir, exist_ok=True)
        if original_frame is not None:
            cv2.imwrite(os.path.join(bundle_dir, "frame_full.jpg"),
                        original_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if vehicle_crop is not None:
            cv2.imwrite(os.path.join(bundle_dir, "vehicle.jpg"),
                        vehicle_crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if raw_plate_crop is not None:
            cv2.imwrite(os.path.join(bundle_dir, "plate_raw.jpg"),
                        raw_plate_crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if enhanced_plate_crop is not None:
            cv2.imwrite(os.path.join(bundle_dir, "plate_enhanced.jpg"),
                        enhanced_plate_crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        import json
        with open(os.path.join(bundle_dir, "bundle.json"), "w") as f:
            json.dump({
                "camera_id": camera_id,
                "track_id": track_id,
                "created_at": ts,
                "quality": quality.to_dict() if quality else None,
                "ocr_results_by_engine": ocr_results_by_engine,
                "final_decision": final_decision,
            }, f, ensure_ascii=False, indent=2)
        return bundle_dir
    except Exception:
        logger.exception("save_debug_bundle a échoué (non bloquant)")
        return None


# ═════════════════════════════════════════════════════════════════════
# Fusion pondérée par moteur — utilisée par anpr_tracker.best_reading
# ═════════════════════════════════════════════════════════════════════
ENGINE_WEIGHTS: dict[str, float] = {
    "fast-alpr": 1.0,
    "plate-recognizer": 1.0,
    "openalpr": 0.95,
    "paddle-ocr": 0.9,
    "easyocr": 0.75,
    "tesseract": 0.55,
    "opencv-ocr": 0.5,
    "google-vision": 0.95,
    "azure-vision": 0.95,
    "codeproject-ai": 0.85,
    "anpr-eps": 0.85,
}


def engine_weight(name: str) -> float:
    """Poids d'un moteur OCR (défaut 0.7 pour un moteur inconnu)."""
    return float(ENGINE_WEIGHTS.get((name or "").lower(), 0.7))
