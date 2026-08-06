"""Tests v0.5.1.c · Multi-plugin events + Recherche véhicule enrichie.

Vérifie :
1. `_compute_plugins_used(cam)` retourne les plugins CORE + whitelist caméra.
2. `_prerun_multi_anpr` extrait le dispatch multi-ANPR pour permettre la
   corrélation avec les events YOLO.
3. Le code de `run_downstream` :
   - Attache `plugins_used` aux events et aux plaques
   - Attache `anpr_readings` (multi-moteurs) aux events YOLO par track_id
   - Attache `plate` et `plate_confidence` aux events YOLO
"""
import inspect

import pytest


def test_compute_plugins_used_core_always_present():
    from pipeline_v2.downstream import _compute_plugins_used, _CORE_PLUGINS_ALWAYS_ON
    cam = {"id": "cam1", "enabled_plugins": []}
    result = _compute_plugins_used(cam)
    for p in _CORE_PLUGINS_ALWAYS_ON:
        assert p in result


def test_compute_plugins_used_appends_whitelist():
    from pipeline_v2.downstream import _compute_plugins_used
    cam = {"id": "cam1", "enabled_plugins": ["google-vision", "openalpr"]}
    result = _compute_plugins_used(cam)
    assert "google-vision" in result
    assert "openalpr" in result


def test_compute_plugins_used_no_duplicates():
    from pipeline_v2.downstream import _compute_plugins_used
    cam = {"id": "cam1", "enabled_plugins": ["yolov11", "bytetrack", "google-vision"]}
    result = _compute_plugins_used(cam)
    # yolov11 et bytetrack sont dans CORE ; whitelist ne doit pas les dupliquer
    assert result.count("yolov11") == 1
    assert result.count("bytetrack") == 1
    assert "google-vision" in result


def test_compute_plugins_used_none_whitelist():
    from pipeline_v2.downstream import _compute_plugins_used
    result = _compute_plugins_used({"id": "cam1"})  # pas de enabled_plugins
    assert "yolov11" in result
    assert "fast-alpr" in result


def test_downstream_annotates_events_with_plugins_used():
    """Le code source de run_downstream doit annoter chaque event avec plugins_used."""
    from pipeline_v2.downstream import run_downstream
    src = inspect.getsource(run_downstream)
    # Le champ plugins_used est présent dans les inserts events
    assert '"plugins_used": plugins_used' in src


def test_downstream_annotates_yolo_events_with_anpr_readings():
    """Chaque événement YOLO doit embarquer les lectures multi-moteurs
    de la plaque associée (via track_id)."""
    from pipeline_v2.downstream import run_downstream
    src = inspect.getsource(run_downstream)
    assert '"anpr_readings": anpr_readings' in src
    assert '"plate": best_reading["plate"]' in src


def test_downstream_annotates_plates_with_plugins_used():
    """Les plaques persistées doivent embarquer plugins_used + anpr_readings."""
    from pipeline_v2.downstream import run_downstream
    src = inspect.getsource(run_downstream)
    assert '"plugins_used": plugins_used' in src
    assert '"anpr_readings": all_readings' in src


def test_prerun_multi_anpr_extracted():
    """Le dispatch multi-ANPR doit être extrait en fonction dédiée."""
    from pipeline_v2 import downstream
    assert hasattr(downstream, "_prerun_multi_anpr")


def test_prerun_multi_anpr_closes_on_empty_whitelist():
    """Fermeture stricte : whitelist vide/absente ⇒ aucun dispatch."""
    from pipeline_v2.downstream import _prerun_multi_anpr
    src = inspect.getsource(_prerun_multi_anpr)
    assert "if not _cam_whitelist" in src
    assert "return" in src


def test_track_id_index_populated_before_yolo_events():
    """`_anpr_by_track` doit être rempli AVANT la boucle YOLO events."""
    from pipeline_v2.downstream import run_downstream
    src = inspect.getsource(run_downstream)
    idx_prerun = src.find("_prerun_multi_anpr")
    idx_yolo_events = src.find("Détections YOLO → événements")
    assert idx_prerun < idx_yolo_events, (
        "prerun multi-ANPR doit précéder l'écriture des events YOLO")
