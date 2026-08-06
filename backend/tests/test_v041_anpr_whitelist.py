"""Tests · Bug critique v0.4.1 — ANPR respecte enabled_plugins.

Bug reporté : "FastALPR désactivé sur une caméra. Des plaques sont malgré
tout reconnues." Depuis la refonte v0.4.2, le guard vit dans
``pipeline_v2.camera_worker.CameraWorker._stage_anpr`` (le wrapper
``ai_engine._analyze_frame`` délègue au worker).

Invariants vérifiés :
1. `_analyze_frame(camera_id, frame_bytes, enabled_plugins)` — signature conservée
2. Si `enabled_plugins` non vide ET "fast-alpr" absent → OCR skip complet
3. `_process_camera` passe `cam.get("enabled_plugins")` au worker
"""
import os
import inspect

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "mgvms_test_anpr_whitelist")


def test_analyze_frame_signature_accepts_enabled_plugins():
    """_analyze_frame doit accepter enabled_plugins comme 3ème paramètre."""
    from ai_engine import _analyze_frame
    sig = inspect.signature(_analyze_frame)
    params = list(sig.parameters.keys())
    assert "enabled_plugins" in params, f"missing enabled_plugins in {params}"


def test_analyze_frame_delegates_to_camera_worker():
    """v0.4.2 : le wrapper délègue au CameraWorker (pipeline v2)."""
    from ai_engine import _analyze_frame
    src = inspect.getsource(_analyze_frame)
    assert "runtime.worker(camera_id).analyze" in src.replace("_runtime", "runtime")


def test_stage_anpr_skips_when_whitelist_excludes_fast_alpr():
    """Le bloc ANPR doit être bypassé si fast-alpr absent de la whitelist."""
    from pipeline_v2.camera_worker import CameraWorker
    src = inspect.getsource(CameraWorker._stage_anpr)
    assert '"fast-alpr" not in enabled_plugins' in src
    assert "not skipped" in src


def test_process_camera_passes_enabled_plugins_to_analyze():
    """_process_camera doit passer cam.get('enabled_plugins') au worker."""
    from ai_engine import _process_camera
    src = inspect.getsource(_process_camera)
    assert 'cam.get("enabled_plugins")' in src
    assert "worker.analyze, frame, _enabled" in src


def test_empty_whitelist_keeps_legacy_behavior():
    """Whitelist vide (None ou []) doit laisser passer l'ANPR (legacy)."""
    from pipeline_v2.camera_worker import CameraWorker
    src = inspect.getsource(CameraWorker._stage_anpr)
    # bool(enabled_plugins) = False si None/[] → pas de skip
    assert "bool(enabled_plugins)" in src


def test_no_alpr_predict_when_skipped():
    """Le predict OCR est protégé : early-return si skip (whitelist/qualité)."""
    from pipeline_v2.camera_worker import CameraWorker
    src = inspect.getsource(CameraWorker._stage_anpr)
    lines = src.split("\n")
    guard_idx = next(i for i, l in enumerate(lines)
                     if "if not (ctx.vehicle_rois and _ae._alpr and not skipped):" in l)
    predict_idx = next(i for i, l in enumerate(lines)
                       if "_alpr.predict(" in l)
    assert predict_idx > guard_idx, "OCR predict n'est pas protégé par le guard"
    # Le guard early-return : la ligne suivante contient return
    tail = "\n".join(lines[guard_idx:guard_idx + 3])
    assert "return" in tail
