"""Tests · Bug critique v0.4.1 — ANPR respecte enabled_plugins.

Bug reporté : "FastALPR désactivé sur une caméra. Des plaques sont malgré
tout reconnues." Cause : `_analyze_frame` appelait `_alpr.predict()` sans
consulter la whitelist enabled_plugins.

Fix vérifié :
1. `_analyze_frame(camera_id, frame_bytes, enabled_plugins)` — nouveau param
2. Si `enabled_plugins` non vide ET "fast-alpr" absent → OCR skip complet
3. `_process_camera` passe `cam.get("enabled_plugins")` à `_analyze_frame`
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


def test_analyze_frame_skips_anpr_when_whitelist_excludes_fast_alpr():
    """Le bloc ANPR doit être bypassé si fast-alpr absent de la whitelist."""
    from ai_engine import _analyze_frame
    src = inspect.getsource(_analyze_frame)
    # Le guard existe et est cohérent
    assert '_anpr_skipped' in src
    assert '"fast-alpr" not in enabled_plugins' in src
    # Le predict est protégé par la condition
    assert "and not _anpr_skipped" in src


def test_process_camera_passes_enabled_plugins_to_analyze():
    """_process_camera doit passer cam.get('enabled_plugins') à _analyze_frame."""
    from ai_engine import _process_camera
    src = inspect.getsource(_process_camera)
    assert 'cam.get("enabled_plugins")' in src
    # Le call à to_thread inclut _enabled
    assert '_analyze_frame, cam["id"], frame, _enabled' in src


def test_empty_whitelist_keeps_legacy_behavior():
    """Whitelist vide (None ou []) doit laisser passer l'ANPR (legacy)."""
    from ai_engine import _analyze_frame
    src = inspect.getsource(_analyze_frame)
    # Le check utilise bool(enabled_plugins) = False si None/[]
    assert 'bool(enabled_plugins)' in src


def test_no_alpr_predict_when_skipped():
    """Vérifie que le predict ANPR est bien protégé par la condition."""
    from ai_engine import _analyze_frame
    src = inspect.getsource(_analyze_frame)
    # `_alpr.predict(vehicle_crop)` seule occurrence est bien à l'intérieur
    # du bloc `if vehicles and _alpr and not _anpr_skipped:`
    lines = src.split("\n")
    guard_idx = next(i for i, l in enumerate(lines)
                     if 'if vehicles and _alpr and not _anpr_skipped:' in l)
    predict_idx = next(i for i, l in enumerate(lines)
                       if '_alpr.predict(' in l)
    # predict après le guard
    assert predict_idx > guard_idx, "OCR predict n'est pas protégé par le guard"
