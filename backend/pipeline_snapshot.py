"""Pipeline v2 · Snapshot consolidé Redis — pont pipeline → API (v3.24).

Chantier séparation pipeline IA / serveur API (priorité #1), étape 2b.
L'étape 2a (v3.23) a extrait les constantes pures (arming, QoS thresholds)
dans ai_rules_settings.py. Ce module traite la catégorie (b) : le VRAI
état runtime périodique du pipeline (lecture seule) que la couche API
lisait jusqu'ici en important pipeline_v2.*/ai_engine EN DIRECT — un
import Python qui ne survit pas à une scission en process/conteneurs
séparés.

Principe : le pipeline publie, toutes les SNAPSHOT_INTERVAL_S secondes,
UN SEUL objet JSON consolidé regroupant tout l'état catégorie (b) dans
une clé Redis (``SNAPSHOT_KEY``). Les endpoints API lisent cette clé au
lieu d'importer pipeline_v2/ai_engine.

Découpage strict — c'est tout l'intérêt de ce module :
    _build_snapshot()  → PIPELINE-SIDE uniquement. Importe librement
                          pipeline_v2.*/ai_engine — ne tourne que dans la
                          boucle background du process pipeline.
    snapshot_loop()     → PIPELINE-SIDE. Boucle background, écrit Redis.
    get_snapshot()      → API-SIDE. AUCUN import pipeline_v2/ai_engine, ni
                          transitif. C'est ce qui permet à ce module de
                          rester importable une fois le pipeline scindé
                          dans un process/conteneur séparé.

Catégories (c) écriture/commande et (d) calcul lourd à la demande
(audit 2a) restent hors snapshot — voir routes/health_dashboard.py et
routers.py, endpoints inchangés (invalidate/reset/configure/PUT, etc).

Volontairement EXCLU de ce snapshot (voir rapport de livraison 2b) :
    camera_debug_snapshots (ai_engine.get_debug_snapshot /
    pipeline_v2.camera_worker._last_debug) — ce dict embarque un JPEG
    base64 (``frame_preview``) PAR CAMÉRA (~20-40 Ko). Le dupliquer dans
    une clé rafraîchie toutes les 3 s pour 14 caméras aurait fait
    grossir chaque snapshot de plusieurs centaines de Ko — coûteux en
    bande passante Redis ET en désérialisation pour TOUS les lecteurs
    (même ceux qui ne veulent que ``ai_health``), pour une donnée
    consultée à la demande sur UNE SEULE caméra à la fois. Les 2
    endpoints concernés (``GET /api/ai/debug/{id}``,
    ``GET /api/cameras/{id}/diagnostic``) continuent d'importer
    ``ai_engine`` en direct — inchangé.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from redis_bus import get_redis

logger = logging.getLogger("pipeline_snapshot")

# ── Config ───────────────────────────────────────────────────────────
SNAPSHOT_KEY = "mgvms:pipeline:snapshot"
# Aucune I/O dans _build_snapshot (tout est déjà en mémoire côté pipeline)
# → un intervalle court coûte quasi rien et garde les dashboards "temps réel".
SNAPSHOT_INTERVAL_S = 3.0
# 5x l'intervalle : un pipeline mort/bloqué laisse la clé expirer plutôt que
# de servir indéfiniment une valeur figée aux dashboards.
SNAPSHOT_TTL_S = int(SNAPSHOT_INTERVAL_S * 5)
# v3.24 · Même principe que _CONTAINER_STATUS_STALE_AFTER_S
# (routes/system_admin.py) : dérivé de generated_at, distingue "pipeline
# un peu lent" de "pipeline injoignable" côté UI.
STALE_AFTER_S = 10.0


async def _build_snapshot() -> dict:
    """Construit l'état consolidé catégorie (b). PIPELINE-SIDE UNIQUEMENT.

    Ne tourne que dans snapshot_loop() (boucle background du process
    pipeline) — libre d'importer pipeline_v2/ai_engine.
    """
    from ai_engine import get_ai_health, get_hot_reload_metrics, get_runtime_config
    import ai_engine as _ae
    from pipeline_metrics import pipeline_metrics
    from pipeline_v2.batch_infer import batch_inference
    from pipeline_v2.registry import registry as _graph_registry
    from pipeline_v2.inspector import inspector as _inspector
    from pipeline_v2.camera_worker import runtime as _worker_runtime
    from pipeline_v2 import plate_quality as _pq
    from pipeline_v2.engine_reliability import snapshot as _engine_reliability_snapshot
    from pipeline_v2.anpr_quality import anpr_quality as _anpr_quality
    from pipeline_v2.trace import collector as _trace_collector
    from pipeline_v2.stability_watcher import watcher as _stability_watcher, WINDOWS as _STABILITY_WINDOWS
    from pipeline_v2.camera_state import check_pipeline_activity
    import frame_source as _frame_source

    snap: dict = {"generated_at": time.time()}

    snap["ai_health"] = get_ai_health()
    snap["hot_reload"] = get_hot_reload_metrics()
    snap["runtime_config"] = get_runtime_config()
    snap["pipeline_metrics"] = pipeline_metrics.snapshot()

    # v0.4 · Runtime state réellement appliqué au moteur IA — reprend
    # exactement la logique historique de
    # routes/health_dashboard.py::diagnostics_pipeline_metrics.
    snap["bytetrack_cfg"] = (dict(_ae._bytetrack_cfg) if _ae._bytetrack_cfg
                              else {"enabled": True, "source": "defaults"})
    snap["ai_config_runtime"] = dict(_ae._runtime_config) if _ae._runtime_config else {}

    snap["batch_infer"] = batch_inference.stats()

    snap["pipeline_v2_graphs"] = {
        "cameras": _graph_registry.all_graphs(),
        "stats": _graph_registry.stats(),
    }

    inspector_snap = _inspector.snapshot()
    inspector_snap["runtime"] = _worker_runtime.describe()
    snap["pipeline_inspector"] = inspector_snap

    # v3.27 · Chantier séparation pipeline IA / serveur API, Phase 3 —
    # scission réelle en 2 conteneurs. frame_source.start() n'est appelé
    # que depuis ai_engine.py (aucun autre appelant) : une fois le
    # pipeline dans son propre process, un import direct de frame_source
    # côté API verrait un module vide (aucun worker) — dégradation
    # silencieuse, pas un crash. Publié ici comme le reste de cet état
    # catégorie (b), lu côté API via get_snapshot()["frame_source_status"]
    # (voir routes/health_dashboard.py::diagnostics_frame_source).
    snap["frame_source_status"] = _frame_source.status()

    # v3.29 · Même constat que frame_source ci-dessus, pour le GPU : gpu.py
    # sonde le matériel LOCAL du process (NVML, torch.cuda, TensorRT, ONNX,
    # OpenCV CUDA) — ça n'a de sens que lu depuis le conteneur qui a
    # réellement le GPU. Repéré via la page /gpu et le mini-widget du header
    # (poll 5-10s, /system/gpu et /system/gpu/summary) affichant "Aucun GPU
    # détecté" côté conteneur API alors que le pipeline tourne bien sur GPU.
    from gpu import gpu_summary, gpu_full_info
    snap["gpu_summary"] = gpu_summary()
    snap["gpu_full_info"] = gpu_full_info()

    # v3.34 · Investigation tracking "par saccades" (04/09) : batch_infer.py
    # regroupe les images de plusieurs caméras en un seul appel GPU (voir son
    # docstring) — mais aucun point de mesure n'existait sur le processus
    # RÉEL pour confirmer que ça se produit vraiment à 14 caméras (un test
    # via `docker exec` instancie un singleton neuf, vide, pas le vrai état).
    try:
        from pipeline_v2.batch_infer import batch_inference
        snap["batch_infer_stats"] = batch_inference.stats()
    except Exception:
        snap["batch_infer_stats"] = None

    # Seuils qualité crop plaque : constantes de module jamais réassignées
    # à l'exécution (vérifié dans pipeline_v2/plate_quality.py) — leur
    # valeur COURANTE suffit, pas besoin de re-résoudre le module à chaque
    # lecture API. `debug_enabled()` est en revanche un flag runtime
    # mutable (togglé par PUT /diagnostics/plate-quality/debug) → lu ici.
    snap["plate_quality"] = {
        "thresholds": {
            "min_plate_side_px": _pq.MIN_PLATE_SIDE_PX,
            "min_sharpness": _pq.MIN_SHARPNESS,
            "min_contrast": _pq.MIN_CONTRAST,
            "max_skew_deg": _pq.MAX_SKEW_DEG,
            "good_enough_sharpness": _pq.GOOD_ENOUGH_SHARPNESS,
            "good_enough_contrast": _pq.GOOD_ENOUGH_CONTRAST,
        },
        "engine_weights": dict(_pq.ENGINE_WEIGHTS),
        "debug_mode": {
            "enabled": _pq.debug_enabled(),
            "output_dir": _pq._DEBUG_DIR,
            "env_var": "MGVMS_DEBUG_OCR",
        },
    }

    snap["engine_reliability"] = _engine_reliability_snapshot()

    snap["anpr_quality"] = {
        "config": _anpr_quality.config_dict(),
        "cameras": _anpr_quality.states(),
    }

    # MAX_TRACES = 50 (pipeline_v2/trace.py) et list_recent() sans limite
    # explicite plafonne déjà à 50 → dump intégral du ring buffer sans
    # risque de taille. Le filtrage camera_id/limit se fait côté lecteur
    # (get_snapshot() est API-side et ne doit pas rappeler collector.*).
    snap["traces"] = {
        "sampling_every_n_frames": _trace_collector.get_sampling(),
        "list": _trace_collector.list_recent(),
    }

    snap["stability"] = {
        "windows": {w: _stability_watcher.snapshot(w) for w in _STABILITY_WINDOWS},
        "latest": _stability_watcher.latest(),
    }

    # v3.24 · Étape 3 (camera_state.py) — seul signal_pipeline_activity
    # est un read pipeline_v2 pur (in-memory, zéro I/O réseau) ; réutilise
    # check_pipeline_activity() telle quelle pour ne pas dupliquer sa
    # logique de fraîcheur (30s). Les signaux frame_source/go2rtc/tcp de
    # camera_state.py restent hors snapshot (I/O réseau ou hors
    # pipeline_v2/ai_engine) — voir rapport de livraison.
    camera_activity: dict = {}
    for cid in list(_inspector._cameras.keys()):
        sig = check_pipeline_activity(cid)
        camera_activity[cid] = {"positive": sig.positive, "detail": sig.detail}
    snap["camera_activity"] = camera_activity

    return snap


async def snapshot_loop() -> None:
    """Boucle background PIPELINE-SIDE — écrit le snapshot consolidé dans Redis.

    Même schéma que pipeline_v2.qos_alerts.qos_watcher_loop : une
    itération en échec ne doit jamais arrêter la boucle.
    """
    logger.info("pipeline_snapshot: démarrage (intervalle %.0fs, ttl %ds)",
                SNAPSHOT_INTERVAL_S, SNAPSHOT_TTL_S)
    while True:
        try:
            snap = await _build_snapshot()
            await get_redis().set(SNAPSHOT_KEY, json.dumps(snap, default=str), ex=SNAPSHOT_TTL_S)
        except Exception:
            logger.exception("pipeline_snapshot.snapshot_loop: itération en échec (non bloquant)")
        await asyncio.sleep(SNAPSHOT_INTERVAL_S)


async def get_snapshot() -> Optional[dict]:
    """Lecture API-SIDE du snapshot consolidé.

    AUCUN import pipeline_v2/ai_engine ici, ni transitif — c'est la
    garantie qui permet à ce module de rester importable depuis le
    process API une fois le pipeline scindé dans un process/conteneur
    séparé. Retourne ``None`` si la clé est absente/expirée (pipeline
    pas démarré, Redis indisponible, ou JSON corrompu) — à l'appelant de
    dégrader proprement (ne jamais lever de 500 pour ça).
    """
    try:
        raw = await get_redis().get(SNAPSHOT_KEY)
    except Exception:
        logger.exception("pipeline_snapshot.get_snapshot: Redis indisponible")
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        logger.exception("pipeline_snapshot.get_snapshot: snapshot JSON invalide")
        return None
    try:
        data["stale"] = (time.time() - float(data.get("generated_at", 0))) > STALE_AFTER_S
    except Exception:
        data["stale"] = True
    return data
