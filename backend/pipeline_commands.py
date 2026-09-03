"""Pipeline v2 · Consommateur de commandes Redis — pont API → pipeline (v3.26).

Chantier séparation pipeline IA / serveur API, étapes 2c et 2d. L'étape 2b
(v3.24, pipeline_snapshot.py) a traité la catégorie (b) : l'état runtime
pipeline en LECTURE SEULE, publié périodiquement par le pipeline et lu
par l'API via une clé Redis. L'étape 2c (v3.25) a ajouté la catégorie (c) :
écriture/commande — les endpoints qui jusqu'ici importaient
pipeline_v2.*/ai_engine EN DIRECT pour MUTER un état pipeline (invalidate
un registry, reset un compteur, reconfigurer un contrôleur qualité...).
L'étape 2d (v3.26, ce jalon) ajoute la catégorie (d) : calcul lourd à la
demande — les 2 endpoints qui invoquaient directement `_analyze_frame` /
`analyze_image_local` (analyse ANPR d'une image/d'un frame caméra live)
suivent exactement le même principe RPC + repli.

Principe : plutôt qu'un import Python direct (qui ne survit pas à une
scission en process/conteneurs séparés), l'API publie une commande dans
une file Redis (``redis_bus.QUEUE_PIPELINE_COMMANDS``, BLPOP — voir
redis_bus.py pour le choix BLPOP vs pub/sub) et ce module la consomme
côté pipeline, exécute la mutation, et répond sur une clé Redis dédiée
(RPC synchrone) — ou, pour les signaux fire-and-forget (hot-reload dirty
flags), l'exécute sans répondre.

Découpage strict — même principe que pipeline_snapshot.py :
    _handle_cmd()      → PIPELINE-SIDE uniquement. Importe librement
                          pipeline_v2.*/ai_engine — ne tourne que dans la
                          boucle background du process pipeline.
    _handle_signal()    → PIPELINE-SIDE. Idem, pour les signal_* de
                          ai_engine (hot reload).
    command_loop()      → PIPELINE-SIDE. Boucle background, consomme la
                          file Redis (BLPOP), jamais côté API.

Chaque endpoint API migré (voir routes/health_dashboard.py, routers.py)
appelle ``redis_bus.send_pipeline_command()`` et, si la réponse est
``None`` (Redis indisponible, pipeline pas démarré, timeout), REPLIE sur
son ancien appel Python direct — comportement historique garanti
inchangé tant que pipeline et API partagent le même process. Ce module
est donc, pour l'instant, un chemin best-effort EN PLUS du fallback, pas
un remplacement — il deviendra le seul mécanisme une fois le pipeline
scindé dans un process/conteneur séparé.

Catégorie (d) calcul lourd à la demande : voir `analyze_image_local` et
`anpr_benchmark` ci-dessous — même garantie de repli que (c) sur chaque
endpoint migré (routers.py), avec un timeout RPC plus généreux vu la
nature CPU/GPU-bound de ces 2 commandes.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from redis_bus import get_redis, QUEUE_PIPELINE_COMMANDS

logger = logging.getLogger("pipeline_commands")


async def _handle_cmd(cmd: str, payload: dict) -> dict:
    """Dispatch des commandes RPC catégorie (c). PIPELINE-SIDE UNIQUEMENT.

    Un ``cmd`` inconnu lève ValueError — le caller (command_loop) capture
    et répond ``{"error": ...}`` sans jamais faire planter la boucle.
    """
    if cmd == "registry_invalidate":
        from pipeline_v2.registry import registry as _graph_registry
        camera_id = payload.get("camera_id")
        if camera_id:
            _graph_registry.invalidate(camera_id)
        else:
            _graph_registry.bump_bus_version()
            _graph_registry.invalidate()
        return {"ok": True, "invalidated": camera_id or "all"}

    if cmd == "plate_quality_set_debug":
        from pipeline_v2 import plate_quality as pq
        pq.set_debug_enabled(payload.get("enabled"))
        return {"enabled": pq.debug_enabled(), "output_dir": pq._DEBUG_DIR}

    if cmd == "inspector_reset":
        from pipeline_v2.inspector import inspector as _inspector
        camera_id = payload.get("camera_id")
        _inspector.reset(camera_id)
        return {"ok": True, "reset": camera_id or "all"}

    if cmd == "anpr_quality_configure":
        from pipeline_v2.anpr_quality import anpr_quality
        patch = payload.get("patch") or {}
        anpr_quality.configure(**patch)
        return {"ok": True, "config": anpr_quality.config_dict()}

    if cmd == "anpr_quality_reset":
        from pipeline_v2.anpr_quality import anpr_quality
        camera_id = payload.get("camera_id")
        anpr_quality.reset(camera_id)
        return {"ok": True, "reset": camera_id or "all"}

    if cmd == "traces_set_sampling":
        from pipeline_v2.trace import collector
        # Validation (1<=n<=100000) reste API-side (input sanitization) —
        # voir PUT /diagnostics/traces/sampling. n est déjà validé ici.
        collector.set_sampling(payload.get("n"))
        return {"ok": True, "sampling_every_n_frames": collector.get_sampling()}

    if cmd == "traces_clear":
        from pipeline_v2.trace import collector
        n = collector.clear()
        return {"ok": True, "purged": n}

    if cmd == "stability_clear":
        from pipeline_v2.stability_watcher import watcher
        n = watcher.clear()
        return {"ok": True, "purged": n}

    if cmd == "update_runtime_config":
        # v3.25 · update_runtime_config() retourne dict(_runtime_config) —
        # seulement les clés explicitement surchargées. L'endpoint PUT
        # /ai/config a toujours renvoyé get_runtime_config() (les 6 clés
        # complétées par leurs défauts + device_effective) : reproduire
        # exactement ce comportement ici, pas le retour brut de la mutation.
        from ai_engine import update_runtime_config, get_runtime_config
        await update_runtime_config(payload.get("patch") or {})
        return get_runtime_config()

    if cmd == "analyze_image_local":
        # v3.26 · Étape 2d, catégorie (d) — voir routers.py::analyze_plate.
        # analyze_image_local() est sync/CPU-bound (decode + YOLO + ALPR) ;
        # to_thread pour ne pas bloquer la boucle asyncio du command_loop,
        # même raison que l'appel historique côté API (asyncio.to_thread
        # dans l'ancien analyze_plate / anpr_benchmark).
        import base64
        from ai_engine import analyze_image_local
        image_bytes = base64.b64decode(payload["image_b64"])
        return await asyncio.to_thread(analyze_image_local, image_bytes)

    if cmd == "anpr_benchmark":
        # v3.26 · Étape 2d, catégorie (d) — voir routers.py::anpr_benchmark
        # et _run_anpr_benchmark() ci-dessous (relocation quasi verbatim du
        # corps historique de l'endpoint).
        return await _run_anpr_benchmark(payload)

    raise ValueError(f"commande pipeline inconnue: {cmd!r}")


async def _run_anpr_benchmark(payload: dict) -> dict:
    """Benchmark ANPR complet. PIPELINE-SIDE UNIQUEMENT.

    v3.26 · Étape 2d, catégorie (d) — relocation quasi verbatim du corps
    historique de POST /system/anpr-benchmark (routers.py). Seule la
    validation `iterations` (400 si hors [1,30]) reste API-side (input
    sanitization pure) — voir routers.py::anpr_benchmark. Tout le reste
    (sélection caméra, fetch frame, warm-up, itérations mesurées,
    benchmark multi-moteurs OCR, fusion) est copié à l'identique — pas
    d'appel non plus à un module autre que les imports historiques de
    l'endpoint.

    _handle_cmd() ne peut que lever ValueError (voir command_loop) — les
    2 erreurs HTTP légitimes du corps historique (400 "aucune caméra
    online", 502 "fetch frame échoué") ne sont donc pas levées ici mais
    relayées via un dict sentinelle ``{"__http_error__": {"status": ...,
    "detail": ...}}`` que routers.py::anpr_benchmark traduit en
    HTTPException — ce module reste volontairement libre de toute
    dépendance à FastAPI.
    """
    import time
    from datetime import datetime, timezone
    from database import db
    from gpu import is_gpu_active_for_pipeline, _runtime_pytorch
    from ai_engine import _analyze_frame, _fetch_frame, _model_name, _alpr_model_name

    camera_id = payload.get("camera_id")
    iterations = payload["iterations"]
    engines = payload.get("engines")
    fusion = payload.get("fusion", False)

    # Choix du frame source
    cam_id = camera_id
    frame_bytes = None
    candidates = [cam_id] if cam_id else \
        [c["id"] for c in await db.cameras.find({"status": "online"}, {"_id": 0, "id": 1}).sort("id", 1).to_list(20)]
    if not candidates:
        return {"__http_error__": {"status": 400, "detail": "Aucune caméra online — impossible de récupérer un frame"}}
    # v1.0-rc4 · Le fetch nominal est non-bloquant (wait=0) : on retente
    # quelques fois (le worker produit une frame toutes les ~2 s).
    for attempt in range(4):
        for cid in candidates:
            frame_bytes = await _fetch_frame(cid)
            if frame_bytes is not None:
                cam_id = cid
                break
        if frame_bytes is not None:
            break
        await asyncio.sleep(1.5)
    if frame_bytes is None:
        return {"__http_error__": {"status": 502, "detail": f"Impossible de récupérer un frame ({', '.join(candidates)})"}}
    # Décode UNE fois pour connaître la résolution
    import cv2
    import numpy as np
    if isinstance(frame_bytes, np.ndarray):
        img = frame_bytes
    else:
        arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    resolution = f"{img.shape[1]}x{img.shape[0]}" if img is not None else "unknown"
    # Warm-up (compile CUDA kernels + charge modèles) — 1 passe non comptée
    await asyncio.to_thread(_analyze_frame, cam_id, frame_bytes)
    # N itérations mesurées
    samples: list[dict] = []
    plates_ok = 0
    plates_ko = 0
    plates_total = 0
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = await asyncio.to_thread(_analyze_frame, cam_id, frame_bytes)
        total_ms = (time.perf_counter() - t0) * 1000.0
        tim = result.get("timings", {})
        plates = result.get("plates", [])
        plates_total += len(plates)
        for p in plates:
            plate = p.get("plate", "") or ""
            if len(plate.strip()) >= 4:
                plates_ok += 1
            else:
                plates_ko += 1
        samples.append({
            "total_ms": round(total_ms, 1),
            "yolo_ms": round(tim.get("yolo_ms", 0), 1),
            "alpr_ms": round(tim.get("alpr_ms", 0), 1),
            "detections": len(result.get("detections", [])),
            "plates": len(plates),
        })
    avg = lambda k: round(sum(s[k] for s in samples) / len(samples), 1)  # noqa: E731
    avg_total = avg("total_ms")

    # ── v1.0-rc4 · Benchmark par moteur OCR (multi-plugin) ─────────────
    ocr_engines: list[dict] = []
    fusion_result: Optional[dict] = None
    if engines:
        import psutil
        from plugin_manager.bus import bus as plugin_bus
        from plugin_manager.interfaces import Frame as PluginFrame
        plugin_bus.refresh_lazy_states()
        all_ocr = {e.name: e for e in plugin_bus.list_entries("PlateRecognizer")}
        req = [e.strip() for e in engines.split(",") if e.strip()]
        if any(r in ("all", "tous") for r in req):
            req = list(all_ocr.keys())
        # yolo = détecteur, déjà mesuré via avg_yolo_ms
        req = [r for r in dict.fromkeys(req) if r not in ("yolo", "yolo-detection")]
        pframe = PluginFrame(camera_id=cam_id,
                             timestamp=datetime.now(timezone.utc).isoformat(),
                             numpy_bgr=img, width=img.shape[1], height=img.shape[0])
        proc = psutil.Process()
        best_by_engine: dict[str, dict] = {}
        for name in req:
            entry = all_ocr.get(name)
            if entry is None:
                ocr_engines.append({"engine": name, "available": False, "state": "absent",
                                    "message": "Plugin introuvable sur le bus"})
                continue
            if entry.state != "ready":
                ocr_engines.append({"engine": name, "available": False, "state": entry.state,
                                    "message": entry.state_message or "Non prêt (dépendance ou config manquante)"})
                continue
            times: list[float] = []
            plates_found: list[dict] = []
            err = None
            rss0 = proc.memory_info().rss
            cpu0 = proc.cpu_times()
            wall0 = time.perf_counter()
            for _ in range(iterations):
                t0 = time.perf_counter()
                try:
                    res = await asyncio.wait_for(entry.instance.recognize(pframe, None), timeout=120)
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"[:200]
                    res = []
                times.append((time.perf_counter() - t0) * 1000.0)
                for p in (res or []):
                    if getattr(p, "text", None):
                        plates_found.append({"text": p.text,
                                             "confidence": round(float(p.confidence or 0), 3)})
            wall = max(1e-6, time.perf_counter() - wall0)
            cpu1 = proc.cpu_times()
            cpu_pct = round(((cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)) / wall * 100.0, 1)
            ram_delta_mb = round((proc.memory_info().rss - rss0) / 1e6, 1)
            best = max(plates_found, key=lambda p: p["confidence"], default=None)
            if best:
                best_by_engine[name] = best
            ocr_engines.append({
                "engine": name, "available": True, "state": "ready",
                "iterations": iterations,
                "avg_ms": round(sum(times) / len(times), 1) if times else None,
                "min_ms": round(min(times), 1) if times else None,
                "max_ms": round(max(times), 1) if times else None,
                "cpu_pct": cpu_pct,
                "ram_delta_mb": ram_delta_mb,
                "plates_read_total": len(plates_found),
                "best_plate": best,
                "error": err,
            })
        # Fusion Multi OCR : vote majoritaire caractère par caractère
        if fusion and best_by_engine:
            from collections import Counter
            texts = [b["text"] for b in best_by_engine.values()]
            maxlen = max(len(t) for t in texts)
            voted = []
            for i in range(maxlen):
                chars = [t[i] for t in texts if i < len(t)]
                if chars:
                    voted.append(Counter(chars).most_common(1)[0][0])
            fusion_result = {
                "mode": "vote",
                "text": "".join(voted),
                "engines_used": list(best_by_engine.keys()),
                "avg_confidence": round(sum(b["confidence"] for b in best_by_engine.values())
                                        / len(best_by_engine), 3),
                "candidates": {k: v for k, v in best_by_engine.items()},
            }

    return {
        "camera_id": cam_id,
        "iterations": iterations,
        "resolution_analyzed": resolution,
        "avg_total_ms": avg_total,
        "avg_yolo_ms": avg("yolo_ms"),
        "avg_alpr_ms": avg("alpr_ms"),
        "estimated_fps": round(1000.0 / avg_total, 2) if avg_total > 0 else 0,
        "plates_detected_total": plates_total,
        "plates_ocr_success": plates_ok,
        "plates_ocr_failed": plates_ko,
        "ocr_success_rate": round(plates_ok / plates_total * 100, 1) if plates_total else 0,
        "avg_detections_per_frame": round(sum(s["detections"] for s in samples) / len(samples), 1),
        "gpu_active": is_gpu_active_for_pipeline(),
        "torch_backend": "cuda" if _runtime_pytorch().get("available") else "cpu",
        "torch_version": _runtime_pytorch().get("version"),
        "cuda_version": _runtime_pytorch().get("cuda_version"),
        "yolo_model": _model_name(),
        "alpr_model": _alpr_model_name(),
        "ocr_engines": ocr_engines,
        "fusion_result": fusion_result,
        "samples": samples,
        "run_at": datetime.now(timezone.utc).isoformat(),
    }


def _handle_signal(signal: str, payload: dict) -> None:
    """Dispatch des signaux fire-and-forget (hot reload). PIPELINE-SIDE.

    Sync, pas async — les signal_* de ai_engine sont sync (simples dirty
    flags in-process).
    """
    if signal == "config_changed":
        from ai_engine import signal_config_changed
        signal_config_changed()
    elif signal == "camera_config_changed":
        from ai_engine import signal_camera_config_changed
        signal_camera_config_changed(payload.get("camera_id"))
    elif signal == "camera_topology_changed":
        from ai_engine import signal_camera_topology_changed
        signal_camera_topology_changed(payload.get("camera_id"),
                                        removed=bool(payload.get("removed", False)))
    else:
        logger.warning("pipeline_commands: signal inconnu %s", signal)


async def command_loop() -> None:
    """Boucle background PIPELINE-SIDE — consomme la file de commandes Redis.

    Même schéma que pipeline_snapshot.snapshot_loop : une itération en
    échec ne doit jamais arrêter la boucle.
    """
    logger.info("pipeline_commands: démarrage (file %s)", QUEUE_PIPELINE_COMMANDS)
    while True:
        try:
            r = get_redis()
            item = await r.blpop(QUEUE_PIPELINE_COMMANDS, timeout=5)
            if item is None:
                continue
            _, raw = item
            data = json.loads(raw)
            if "cmd" in data:
                try:
                    result = await _handle_cmd(data["cmd"], data.get("payload") or {})
                except Exception as e:
                    result = {"error": str(e)}
                reply_key = data.get("reply_key")
                if reply_key:
                    try:
                        await r.rpush(reply_key, json.dumps(result, default=str))
                        await r.expire(reply_key, 30)  # nettoyage si jamais rien ne lit la réponse
                    except Exception:
                        logger.exception("pipeline_commands: échec réponse pour reply_key=%s", reply_key)
            elif "signal" in data:
                try:
                    _handle_signal(data["signal"], data.get("payload") or {})
                except Exception:
                    logger.exception("pipeline_commands: échec traitement signal %s", data.get("signal"))
        except Exception:
            logger.exception("pipeline_commands.command_loop: itération en échec (non bloquant)")
            await asyncio.sleep(1)
