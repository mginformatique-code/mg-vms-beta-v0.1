"""v3.38 · Service ANPR isolé — fast-alpr dans son propre process/GPU.

Contexte : jusqu'ici, fast-alpr (onnxruntime-gpu/CUDA) tournait dans le
MÊME process que YOLO (torch/CUDA), protégé par un verrou partagé
(``ai_engine.ALPR_INFERENCE_LOCK == YOLO_INFERENCE_LOCK``) — nécessaire
depuis v3.19, deux runtimes CUDA concurrents sur le même GPU provoquant
des crashs réels ("CUDA error: operation not permitted when stream is
capturing", segfaults). Conséquence mesurée : une lecture ANPR (100ms-1s
par véhicule) bloquait TOUTE autre caméra du parc voulant lancer sa
propre détection YOLO, même sans rapport avec l'ANPR — root cause du
ralentissement généralisé (voir investigation tracking, session du
06-07/09/2026).

Ce service isole fast-alpr dans son propre conteneur, avec son propre
GPU (Quadro K620, voir deploy-app/docker-compose.yml — NVIDIA_VISIBLE_DEVICES
épinglé sur son UUID) : plus de contexte CUDA partagé avec YOLO, donc
plus besoin du verrou commun pour ce chemin. Isolation par CONTENEUR
(pas par ``device_id`` choisi dans le code) — testé en direct sur ce
serveur : passer un ``device_id`` explicite à onnxruntime s'est révélé
non fiable (échecs cuDNN même pour le device par défaut). Ce process ne
voit qu'UN SEUL GPU (celui que Docker lui attribue) donc le code reste
identique à l'existant : pas de device_id à préciser, c'est le seul
visible ici.

Volontairement minimal : pas de DB, pas de Redis, pas de plugin bus —
juste fast-alpr derrière une route HTTP, pour démarrer vite et ne
dépendre de rien d'autre que le nécessaire.
"""
import logging

import cv2
import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("anpr_service")

app = FastAPI(title="MG-VMS ANPR Service (isolé)")
_alpr = None


@app.on_event("startup")
def _load() -> None:
    global _alpr
    from fast_alpr import ALPR
    try:
        _alpr = ALPR(detector_model="yolo-v9-t-384-license-plate-end2end",
                      detector_providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                      ocr_model="european-plates-mobile-vit-v2-model",
                      ocr_device="cuda")
    except Exception:
        logger.exception("fast-alpr GPU indisponible dans le service dédié — repli CPU")
        _alpr = ALPR(detector_model="yolo-v9-t-384-license-plate-end2end",
                      ocr_model="european-plates-mobile-vit-v2-model")
    try:
        providers = _alpr.detector.detector.model.get_providers()
    except Exception:
        providers = ["?"]
    logger.info("anpr_service : fast-alpr chargé (providers=%s)", providers)


@app.get("/health")
def health():
    if _alpr is None:
        return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True}


@app.post("/recognize")
async def recognize(request: Request):
    """Corps = JPEG brut (crop véhicule). Retourne {"results": [...]}
    au même format que ``PlateOcrResult`` (voir plate_recognizer.py)."""
    body = await request.body()
    if _alpr is None or not body:
        return JSONResponse({"results": []})
    arr = np.frombuffer(body, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return JSONResponse({"results": []})
    try:
        raw = list(_alpr.predict(img))
    except Exception:
        logger.exception("anpr_service: erreur predict()")
        return JSONResponse({"results": []})
    results = []
    for r in raw:
        if not getattr(r, "ocr", None) or not r.ocr.text:
            continue
        bb = r.detection.bounding_box
        results.append({
            "text": str(r.ocr.text),
            "confidence": float(r.ocr.confidence),
            "bbox_in_roi": [float(bb.x1), float(bb.y1), float(bb.x2), float(bb.y2)],
        })
    return JSONResponse({"results": results})
