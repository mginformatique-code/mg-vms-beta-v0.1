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
