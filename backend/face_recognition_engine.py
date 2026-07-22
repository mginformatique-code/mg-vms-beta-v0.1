"""MG-VMS — Reconnaissance faciale (production).

Backend basé sur `insightface` (ONNX, CPU par défaut). 100% local, aucune API externe.

Flux :
1. L'admin déclare un visage (nom + watchlist).
2. Il upload une photo → InsightFace extrait un embedding (vecteur 512d).
3. À l'analyse IA (`ai_engine._process_camera`), les frames sont scannées ; chaque visage
   est comparé à la base via cosine similarity ; si >= threshold → événement + audit.

Dégrade proprement si `insightface` n'est pas installé (endpoint retournent 503 ciblé).
"""
from __future__ import annotations

import io
import base64
import logging
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_MODEL = None  # instance InsightFace FaceAnalysis (chargée à la demande)
_IMPORT_ERROR: Optional[str] = None


def _try_import():
    """Charge insightface la première fois. Retourne (ok, error_message)."""
    global _MODEL, _IMPORT_ERROR
    if _MODEL is not None:
        return True, None
    if _IMPORT_ERROR is not None:
        return False, _IMPORT_ERROR
    try:
        import insightface
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_s", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(320, 320))
        _MODEL = app
        logger.info("Face recognition : InsightFace 'buffalo_s' chargé (CPU)")
        return True, None
    except Exception as exc:  # noqa: BLE001
        _IMPORT_ERROR = f"{exc.__class__.__name__}: {exc}"
        logger.warning("Face recognition indisponible : %s", _IMPORT_ERROR)
        return False, _IMPORT_ERROR


def availability() -> dict:
    """Retourne l'état d'installation pour l'UI (sans forcer le download du modèle)."""
    try:
        import insightface  # noqa: F401
        return {"installed": True, "provider": "insightface",
                "notes": "InsightFace (ONNX buffalo_s) — CPU. Le modèle sera téléchargé au premier upload de photo."}
    except ImportError as exc:
        return {"installed": False, "provider": None,
                "notes": f"insightface non installé — {exc}. "
                         "Pour activer : `pip install insightface onnxruntime` (nécessite gcc/python-dev)."}


def extract_embedding(image_bytes: bytes) -> tuple:
    """Extrait l'embedding facial d'une image. Retourne (embedding_list, meta) ou (None, error)."""
    ok, err = _try_import()
    if not ok:
        return None, {"error": "Bibliothèque non installée", "detail": err}
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)[:, :, ::-1]  # RGB → BGR pour InsightFace
    except (OSError, ValueError) as exc:
        return None, {"error": "Image invalide", "detail": str(exc)}

    faces = _MODEL.get(arr)
    if not faces:
        return None, {"error": "Aucun visage détecté dans la photo"}
    if len(faces) > 1:
        return None, {"error": f"{len(faces)} visages détectés — n'importez qu'une seule personne à la fois"}
    face = faces[0]
    emb = face.normed_embedding.astype(np.float32).tolist()
    x1, y1, x2, y2 = [int(v) for v in face.bbox]
    return emb, {
        "bbox": [x1, y1, x2, y2],
        "det_score": float(face.det_score),
        "gender": int(getattr(face, "gender", -1)) if getattr(face, "gender", None) is not None else None,
        "age": int(getattr(face, "age", -1)) if getattr(face, "age", None) is not None else None,
    }


def analyze_frame(bgr_frame: np.ndarray, known: list, threshold: float = 0.55) -> list:
    """Compare tous les visages détectés dans une frame BGR à la base de visages connus.

    known: liste de {"id", "name", "watchlist", "embedding": [512 floats]}
    Retourne : liste de {"face_id", "name", "watchlist", "similarity", "bbox", "det_score"}
    """
    ok, _ = _try_import()
    if not ok or not known:
        return []
    faces = _MODEL.get(bgr_frame)
    if not faces:
        return []
    known_matrix = np.array([k["embedding"] for k in known], dtype=np.float32)
    out = []
    for face in faces:
        emb = face.normed_embedding.astype(np.float32)
        # Similarité cosinus (les embeddings sont L2-normalisés : dot = cosine)
        sims = known_matrix @ emb
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        if best_sim < threshold:
            match = {"face_id": None, "name": "Inconnu", "watchlist": False,
                     "similarity": round(best_sim, 3)}
        else:
            k = known[best_idx]
            match = {"face_id": k["id"], "name": k["name"],
                     "watchlist": bool(k.get("watchlist")),
                     "similarity": round(best_sim, 3)}
        x1, y1, x2, y2 = [int(v) for v in face.bbox]
        match.update({"bbox": [x1, y1, x2, y2], "det_score": float(face.det_score)})
        out.append(match)
    return out


def image_to_thumbnail(image_bytes: bytes, size: int = 120) -> Optional[str]:
    """Retourne une data-URL JPEG (~10 kB) pour affichage des visages dans l'UI."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except (OSError, ValueError):
        return None
    img.thumbnail((size, size))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
