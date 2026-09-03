"""v0.8-rc2 · Camera Advisor — recommandations automatiques par caméra.

Exploite les données existantes (Health Score, Crop Quality, Pipeline
Inspector, Engine Reliability, benchmarks) pour produire des conseils
actionables à l'intégrateur — sans faire d'IA lourde, juste des règles
métier explicites et auditables.
"""
from __future__ import annotations

import logging
import statistics

from database import db

logger = logging.getLogger("camera_advisor")


async def advise(camera_id: str) -> dict:
    cam = await db.cameras.find_one({"id": camera_id}, {"_id": 0})
    if not cam:
        return {"error": "camera_not_found", "camera_id": camera_id}

    recs: list[dict] = []
    from services.camera_health import compute_health
    health = await compute_health(camera_id)
    signals = health.get("signals", {})

    # 1. FPS très bas
    fps_hint = (signals.get("fps") or {}).get("pct", 100)
    if fps_hint < 40:
        recs.append({
            "severity": "warning", "category": "streaming",
            "title": "FPS très inférieur à l'attendu",
            "advice": "Vérifier la bande passante, le codec H.265 vs H.264 "
                     "et le débit du sub-stream. Envisager une résolution HD "
                     "1080p plutôt que 4K si l'ANPR est le cas d'usage principal.",
        })

    # 2. Qualité OCR moyenne faible
    ocr_pct = (signals.get("ocr_quality") or {}).get("pct", 100)
    if ocr_pct < 55:
        recs.append({
            "severity": "warning", "category": "installation",
            "title": "Qualité OCR faible sur cette caméra",
            "advice": "3 causes probables : (1) caméra trop haute ou angle "
                     "trop plongeant — repositionner à < 4 m avec un angle < 25°. "
                     "(2) éclairage insuffisant — ajouter un projecteur IR ou "
                     "activer le mode couleur nuit. (3) résolution insuffisante "
                     "sur la zone plaque — zoomer optiquement.",
        })

    # 3. RTSP instable
    rtsp_pct = (signals.get("rtsp") or {}).get("pct", 100)
    if rtsp_pct < 60:
        recs.append({
            "severity": "critical", "category": "network",
            "title": "Flux RTSP instable ou coupé",
            "advice": "Vérifier le câble Ethernet / la connexion Wi-Fi, "
                     "l'alimentation PoE (budget suffisant sur le switch ?), "
                     "et l'IP de la caméra (fixe recommandée, jamais DHCP).",
        })

    # 4. Pipeline > SLA
    latency_pct = (signals.get("latency_p95") or {}).get("pct", 100)
    if latency_pct < 60:
        recs.append({
            "severity": "warning", "category": "performance",
            "title": "Pipeline dépasse le SLA 200 ms sur cette caméra",
            "advice": "Passer YOLO à yolov8s (au lieu de m/l), réduire la "
                     "fréquence d'analyse (interval_seconds ≥ 0.3), ou "
                     "désactiver les moteurs OCR les moins performants "
                     "(voir Engine Reliability).",
        })

    # 5. Pas d'ONVIF heartbeat
    onvif_pct = (signals.get("onvif_freshness") or {}).get("pct", 100)
    if onvif_pct < 50:
        recs.append({
            "severity": "info", "category": "config",
            "title": "ONVIF non détecté",
            "advice": "Activer ONVIF dans l'interface web de la caméra, "
                     "créer un utilisateur ONVIF dédié, puis re-configurer "
                     "la caméra avec ses credentials. Cela débloque : "
                     "capabilities auto, PTZ, presets, events, snapshot API.",
        })

    # 6. Analyse Engine Reliability : moteur sous-performant identifié
    # v3.29 · Chantier séparation pipeline IA / serveur API — audit
    # complémentaire (au-delà du périmètre 2a-2d) : import direct
    # pipeline_v2.engine_reliability, module vide/dormant une fois le
    # pipeline dans son propre conteneur (v3.27) — dégradation silencieuse
    # (aucune recommandation ocr_tuning générée), pas un crash. Déjà
    # publié dans le snapshot (catégorie b, présent depuis 2b).
    try:
        from pipeline_snapshot import get_snapshot
        _snap = await get_snapshot()
        snap = (_snap or {}).get("engine_reliability") or {}
        cam_engines = snap.get(camera_id, {})
        engines_by_acc = sorted(cam_engines.items(),
                                 key=lambda kv: kv[1].get("rolling_accuracy", 0),
                                 reverse=True)
        if len(engines_by_acc) >= 2:
            best_name, best = engines_by_acc[0]
            worst_name, worst = engines_by_acc[-1]
            if best["rolling_accuracy"] - worst["rolling_accuracy"] > 0.3 and \
               worst["reads_recent"] >= 10:
                recs.append({
                    "severity": "info", "category": "ocr_tuning",
                    "title": f"Moteur OCR « {worst_name} » sous-performe sur cette caméra",
                    "advice": f"« {best_name} » atteint {best['rolling_accuracy']*100:.0f} % "
                             f"vs {worst['rolling_accuracy']*100:.0f} % pour « {worst_name} ». "
                             f"Envisager de désactiver « {worst_name} » sur cette caméra "
                             "via `PUT /api/plugins/anpr/cameras/{id}` pour économiser du CPU.",
                })
    except Exception:
        pass

    # 7. Map Center : coordonnées absentes
    if not cam.get("lat") or not cam.get("lng"):
        recs.append({
            "severity": "info", "category": "map",
            "title": "Coordonnées géographiques manquantes",
            "advice": "Renseigner lat/lng dans la fiche caméra pour bénéficier "
                     "du Map Center + Installation Quality Report (couverture "
                     "théorique vs réelle, zones mortes, orientation).",
        })

    return {
        "camera_id": camera_id,
        "camera_name": cam.get("name"),
        "health_score": health.get("score"),
        "health_band": health.get("band"),
        "recommendations": recs,
        "count_by_severity": {
            "critical": sum(1 for r in recs if r["severity"] == "critical"),
            "warning": sum(1 for r in recs if r["severity"] == "warning"),
            "info": sum(1 for r in recs if r["severity"] == "info"),
        },
    }


async def advise_all() -> list:
    cams = await db.cameras.find({}, {"_id": 0, "id": 1}).to_list(500)
    return [await advise(c["id"]) for c in cams]
