"""Endpoints Plugin Manager NG — bus, policy, multi-ANPR (chapitre 11 §11.6.1).

Endpoints exposés (montés sur /api/* — accessibles aussi via /api/v1/*
grâce au middleware `ApiVersionAliasMiddleware` de `server.py`) :

  GET  /api/plugins/bus                          → liste des plugins sur le bus
  POST /api/plugins/bus/{name}/enable            → active un plugin
  POST /api/plugins/bus/{name}/disable           → désactive un plugin

  GET  /api/plugins/policy                       → politique actuelle
  PUT  /api/plugins/policy/anpr                  → change mode/threshold ANPR
  PUT  /api/plugins/policy/frame-analyzer        → change parallel/timeout

  POST /api/plugins/test/multi-anpr              → simule un cycle multi-ANPR
                                                    (utile pour valider la fusion sans caméra)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, Body, Depends, HTTPException

from auth import require_permission
from plugin_manager import (
    apply_policy,
    bus,
    policy,
    Frame,
    VALID_MODES,
)
from plugin_manager.builtin import MockPlatePlugin

logger = logging.getLogger("routes.plugins_bus")

plugins_bus_router = APIRouter(prefix="/api", tags=["plugins-ng"])


# ─────────────────────────── BUS ────────────────────────────

@plugins_bus_router.get("/plugins/bus")
async def bus_status(user: dict = Depends(require_permission("view_live"))):
    """État du bus multi-plugin (chapitre 11 §11.4.1).

    Retourne la liste des plugins **actuellement instanciés** sur le bus
    (différent de `/api/plugins` qui expose le catalogue déclaratif).
    Chaque entrée inclut les compteurs runtime (`calls`, `errors`,
    `timeouts`, `last_ms`).
    """
    return {
        "entries": bus.summary(),
        "counts": {
            "total": len(bus.list_entries()),
            "frame_analyzers": len(bus.list_entries("FrameAnalyzer")),
            "plate_recognizers": len(bus.list_entries("PlateRecognizer")),
            "event_consumers": len(bus.list_entries("EventConsumer")),
            "enabled": sum(1 for e in bus.list_entries() if e.enabled),
        },
        "default_timeout_s": bus.default_timeout_s,
    }


@plugins_bus_router.post("/plugins/bus/{name}/enable")
async def bus_enable(name: str, user: dict = Depends(require_permission("technician"))):
    if not bus.set_enabled(name, True):
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' non enregistré sur le bus")
    return {"name": name, "enabled": True}


@plugins_bus_router.post("/plugins/bus/{name}/disable")
async def bus_disable(name: str, user: dict = Depends(require_permission("technician"))):
    if not bus.set_enabled(name, False):
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' non enregistré sur le bus")
    return {"name": name, "enabled": False}


@plugins_bus_router.get("/plugins/loader")
async def loader_status(user: dict = Depends(require_permission("view_live"))):
    """Plugins découverts par le loader dynamique (manifest YAML).

    Retourne pour chaque plugin :
      - `loaded` : true si register() a réussi
      - `error` : détail si le chargement a échoué (isolation — le core continue)
      - `has_config_schema` : true si un `config/schema.json` est fourni

    Endpoint utilisé par la page Plugins NG pour distinguer les plugins
    chargés dynamiquement (avec manifest) des wrappers builtin fallback.
    """
    from plugin_manager.loader import loader as pl
    return {
        "plugins_dir": str(pl.plugins_dir),
        "loaded": pl.loaded(),
    }


@plugins_bus_router.get("/plugins/loader/{name}/schema")
async def loader_config_schema(name: str, user: dict = Depends(require_permission("view_live"))):
    """Retourne le JSON Schema de configuration d'un plugin chargé dynamiquement."""
    from plugin_manager.loader import loader as pl
    schema = pl.get_config_schema(name)
    if schema is None:
        raise HTTPException(status_code=404, detail=f"Aucun schéma pour plugin '{name}'")
    return schema


@plugins_bus_router.get("/plugins/{name}/config")
async def get_plugin_config(name: str, user: dict = Depends(require_permission("technician"))):
    """Retourne la config utilisateur persistée du plugin (dict vide si jamais configuré).

    Les valeurs sensibles (contenant `password`, `token`, `secret`, `api_key`,
    `webhook`, ...) sont masquées en `***`. Pour les mettre à jour il faut
    renvoyer la vraie valeur via PUT (valeur `"***"` = inchangée).
    """
    from plugin_manager.config_store import store, _is_sensitive
    from plugin_manager.loader import loader as pl
    cfg = store.get(name)  # secrets déchiffrés
    schema = pl.get_config_schema(name)
    masked = dict(cfg)
    for k in list(masked.keys()):
        if _is_sensitive(k) and masked[k]:
            masked[k] = "***"
    return {"name": name, "config": masked, "has_schema": schema is not None,
            "keys_set": [k for k, v in cfg.items() if v]}


@plugins_bus_router.put("/plugins/{name}/config")
async def set_plugin_config(
    name: str,
    payload: dict = Body(...),
    user: dict = Depends(require_permission("technician")),
):
    """Persiste la config d'un plugin et déclenche un reload à chaud.

    Body : le dict de configuration attendu par le schéma du plugin. Les
    valeurs à `"***"` sont considérées inchangées (préservation des secrets).
    """
    from plugin_manager.loader import loader as pl
    from plugin_manager.config_store import store
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="body doit être un objet")
    current = store.get(name)
    # Fusionne : "***" => on garde la valeur existante
    merged = dict(current)
    for k, v in payload.items():
        if isinstance(v, str) and v == "***":
            continue
        merged[k] = v
    err = await pl.reload_config(name, merged)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"name": name, "reloaded": True, "keys_set": [k for k, v in merged.items() if v]}


@plugins_bus_router.post("/plugins/{name}/install-deps")
async def install_plugin_deps(
    name: str,
    payload: dict = Body(default={}),
    user: dict = Depends(require_permission("admin")),
):
    """Lance l'installation `pip install` des deps du plugin en arrière-plan.

    Body optionnel : `{"allow_upgrade_deps": true}` pour désactiver `--no-deps`
    (risqué — peut casser d'autres plugins si upgrade numpy/opencv). Par défaut
    l'install est protégée (`--no-deps`).

    Retourne immédiatement un `status: running`. Poll via
    `GET /plugins/{name}/install-status` pour l'avancement.
    """
    from plugin_manager.loader import loader as pl
    allow = bool((payload or {}).get("allow_upgrade_deps", False))
    job = await pl.install_dependencies(name, allow_upgrade_deps=allow)
    if job.get("status") == "error":
        raise HTTPException(status_code=400, detail=job.get("error"))
    return job


@plugins_bus_router.get("/plugins/{name}/install-status")
async def get_install_status(name: str, user: dict = Depends(require_permission("technician"))):
    """Retourne le statut du dernier job d'installation des deps du plugin."""
    from plugin_manager.loader import loader as pl
    job = pl.get_install_status(name)
    if job is None:
        return {"status": "idle", "log": "", "deps": []}
    return job


# ─────────────────────── PIPELINE (Detector → Tracker → Segmenter → Business) ────

def _serialize_pipeline(pr) -> dict:
    """Sérialise un PipelineResult pour JSON."""
    return {
        "camera_id": pr.camera_id,
        "timestamp": pr.timestamp,
        "detections": [
            {"label": d.label, "label_fr": getattr(d, "label_fr", None),
             "confidence": d.confidence, "bbox": list(d.bbox),
             "track_id": getattr(d, "track_id", None)}
            for d in pr.detections
        ],
        "tracks": [
            {"track_id": t.track_id, "label": t.label,
             "confidence": t.confidence, "bbox": list(t.bbox),
             "age": t.age}
            for t in pr.tracks
        ],
        "masks": [
            {"label": m.label, "confidence": m.confidence,
             "bbox": list(m.bbox), "area_px": m.area_px}
            for m in pr.masks
        ],
        "business_events": pr.business_events,
        "timing_ms": pr.timing_ms,
        "plugins_used": pr.plugins_used,
    }


@plugins_bus_router.post("/plugins/pipeline/test")
async def pipeline_test(
    payload: dict = Body(default={}),
    user: dict = Depends(require_permission("technician")),
):
    """Exécute un cycle pipeline complet sur une frame de test.

    Body :
    ```json
    {
      "run_segmentation": false,
      "run_business": true,
      "emit_events": false,
      "detections_seed": [
        {"label":"person","confidence":0.9,"bbox":[100,100,200,300]},
        {"label":"car","confidence":0.85,"bbox":[300,150,500,250]}
      ]
    }
    ```

    Si `detections_seed` fourni, il court-circuite les FrameAnalyzers (utile
    pour tester Tracker+Business sans avoir de modèle YOLO chargé). Sinon
    utilise la vraie chaîne complète sur une frame noire 640×480.
    """
    import numpy as np
    from datetime import datetime, timezone
    from plugin_manager import bus, Frame
    from plugin_manager.interfaces import Detection

    arr = np.zeros((480, 640, 3), dtype=np.uint8)
    frame = Frame(
        camera_id=payload.get("camera_id", "test-pipeline"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        numpy_bgr=arr, width=640, height=480,
    )

    seed = payload.get("detections_seed")
    if seed:
        # Simule une détection en injectant directement dans le pipeline
        # via un plugin FrameAnalyzer temporaire.
        from plugin_manager.interfaces import FrameAnalyzer, AnalysisResult
        class _SeedAnalyzer(FrameAnalyzer):
            name = "__pipeline_seed"
            version = "test"
            async def analyze(self, frame, camera_config):
                dets = [Detection(
                    label=d.get("label", "?"),
                    label_fr=d.get("label_fr"),
                    confidence=float(d.get("confidence", 0.0)),
                    bbox=tuple(d.get("bbox", (0, 0, 0, 0))),
                ) for d in seed]
                return AnalysisResult(detections=dets, timing_ms=0)
        seed_analyzer = _SeedAnalyzer()
        # Registre temporaire — désactive les vrais detectors pendant le test
        real_fa = {e.name: e.enabled for e in bus.list_entries("FrameAnalyzer")}
        for name in real_fa:
            bus.set_enabled(name, False)
        bus.register("__pipeline_seed", seed_analyzer, order=1)
        try:
            pr = await bus.dispatch_pipeline(
                frame,
                run_segmentation=bool(payload.get("run_segmentation", False)),
                run_business=bool(payload.get("run_business", True)),
                emit_events=bool(payload.get("emit_events", False)),
            )
        finally:
            bus.unregister("__pipeline_seed")
            for name, en in real_fa.items():
                bus.set_enabled(name, en)
    else:
        pr = await bus.dispatch_pipeline(
            frame,
            run_segmentation=bool(payload.get("run_segmentation", False)),
            run_business=bool(payload.get("run_business", True)),
            emit_events=bool(payload.get("emit_events", False)),
        )
    return _serialize_pipeline(pr)


# ─────────────────────── POLICY ───────────────────────

@plugins_bus_router.get("/plugins/policy")
async def get_policy(user: dict = Depends(require_permission("view_live"))):
    """Politique globale multi-plugin (mode ANPR, timeout, parallélisme)."""
    return policy.snapshot()


@plugins_bus_router.put("/plugins/policy/anpr")
async def set_anpr_policy(
    payload: dict = Body(...),
    user: dict = Depends(require_permission("technician")),
):
    """Change la politique multi-ANPR (§11.6.1).

    Body :
    ```json
    {"mode": "cascade|highest|compare|vote",
     "cascade_threshold": 0.85,
     "order": ["plate-recognizer", "paddle-ocr", "fast-alpr"]}
    ```
    """
    try:
        new = policy.set_anpr_policy(
            mode=payload.get("mode"),
            cascade_threshold=payload.get("cascade_threshold"),
            order=payload.get("order"),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return new


@plugins_bus_router.put("/plugins/policy/frame-analyzer")
async def set_frame_policy(
    payload: dict = Body(...),
    user: dict = Depends(require_permission("technician")),
):
    """Change la politique multi-FrameAnalyzer (parallélisme + timeout)."""
    try:
        new = policy.set_frame_policy(
            parallel=payload.get("parallel"),
            timeout_s=payload.get("timeout_s"),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return new


# ─────────────────────── TEST / DEMO ───────────────────────

def _fake_frame() -> Frame:
    """Construit une frame factice 640x480 noire (pour endpoint test)."""
    arr = np.zeros((480, 640, 3), dtype=np.uint8)
    return Frame(
        camera_id="test",
        timestamp=datetime.now(timezone.utc).isoformat(),
        numpy_bgr=arr,
        width=640,
        height=480,
    )


@plugins_bus_router.post("/plugins/test/multi-anpr")
async def test_multi_anpr(
    payload: dict = Body(default={}),
    user: dict = Depends(require_permission("technician")),
):
    """Simule un cycle multi-ANPR pour valider la fusion sans caméra.

    Body optionnel :
    ```json
    {
      "inject_mocks": [
        {"engine":"paddle-ocr","text":"AB-123-CD","confidence":0.91},
        {"engine":"plate-recognizer","text":"AB-123-CD","confidence":0.98},
        {"engine":"easyocr","text":"AB-125-CD","confidence":0.72}
      ],
      "mode": "cascade"          // override policy pour ce test uniquement
    }
    ```

    Si `inject_mocks` est fourni, ces mocks remplacent temporairement les
    plugins réels sur le bus. Utile pour QA multi-ANPR sans quota cloud.
    """
    frame = _fake_frame()

    # Snapshot des plugins réels + injection éventuelle de mocks
    mocks_injected: list[str] = []
    real_states: dict = {}
    try:
        if payload.get("inject_mocks"):
            for entry in bus.list_entries("PlateRecognizer"):
                real_states[entry.name] = entry.enabled
                bus.set_enabled(entry.name, False)
            for i, m in enumerate(payload["inject_mocks"]):
                name = f"__test_{m.get('engine', f'mock{i}')}"
                inst = MockPlatePlugin(
                    engine_name=m.get("engine", f"mock{i}"),
                    text=str(m.get("text", "AB-123-CD")),
                    confidence=float(m.get("confidence", 0.9)),
                    processing_ms=int(m.get("processing_ms", 5)),
                )
                bus.register(name, inst, order=100 + i)
                mocks_injected.append(name)

        current = policy.get_anpr_policy()
        mode = payload.get("mode") or current["mode"]
        if mode not in VALID_MODES:
            raise HTTPException(status_code=422, detail=f"mode invalide: {mode}")
        threshold = float(payload.get("cascade_threshold", current["cascade_threshold"]))

        # cascade → dispatch séquentiel avec stop-at
        cascade_stop = threshold if mode == "cascade" else None
        raw = await bus.dispatch_plate(frame, cascade_stop_at=cascade_stop)

        fused = apply_policy(mode, raw, threshold=threshold)
        # sérialise le PlateResult final
        f = fused.get("final")
        if f is not None:
            fused["final"] = {
                "text": f.text,
                "confidence": f.confidence,
                "engine": f.engine,
                "processing_ms": f.processing_ms,
                "country_hint": f.country_hint,
            }
        return {
            "policy_used": {"mode": mode, "cascade_threshold": threshold},
            "engines_called": [name for name, _ in raw],
            **fused,
        }
    finally:
        # Nettoyage : retire les mocks, restaure les vrais plugins
        for m in mocks_injected:
            bus.unregister(m)
        for name, was_enabled in real_states.items():
            bus.set_enabled(name, was_enabled)
