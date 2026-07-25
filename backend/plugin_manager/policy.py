"""Politique multi-plugin (globale + par caméra) — PoC v2.30.

Configure comment le Plugin Manager combine les résultats des plugins
`PlateRecognizer` (mode cascade, highest, compare, vote) et gère la
sélection des `FrameAnalyzer` actifs (§11.6.2).

En v2.30 (PoC) : politique globale en mémoire, persistée sur disque JSON.
En v3.0 : politique par caméra stockée dans `db.cameras.plugins`.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .fusion import (
    DEFAULT_CASCADE_THRESHOLD,
    MODE_CASCADE,
    VALID_MODES,
)

logger = logging.getLogger("plugin_policy")

POLICY_PATH = Path("/app/backend/data/plugin_policy.json")

DEFAULT_POLICY = {
    "anpr": {
        "mode": MODE_CASCADE,
        "cascade_threshold": DEFAULT_CASCADE_THRESHOLD,
        "order": [],  # engines par ordre de priorité (vide = ordre d'enregistrement)
    },
    "frame_analyzer": {
        "parallel": True,
        "timeout_s": 5.0,
    },
}


class PolicyStore:
    """Store thread-safe de la politique multi-plugin."""

    def __init__(self):
        self._lock = threading.Lock()
        self._policy = dict(DEFAULT_POLICY)
        self._policy["anpr"] = dict(DEFAULT_POLICY["anpr"])
        self._policy["frame_analyzer"] = dict(DEFAULT_POLICY["frame_analyzer"])
        self._load()

    def _load(self):
        try:
            if POLICY_PATH.exists():
                data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
                # Merge défensif
                for section, values in data.items():
                    if section in self._policy and isinstance(values, dict):
                        self._policy[section].update(values)
                logger.info("plugin_policy.loaded path=%s", POLICY_PATH)
        except Exception as e:  # pragma: no cover
            logger.warning("plugin_policy.load_error err=%s", e)

    def _persist(self):
        try:
            POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
            POLICY_PATH.write_text(json.dumps(self._policy, indent=2), encoding="utf-8")
        except Exception as e:  # pragma: no cover
            logger.warning("plugin_policy.save_error err=%s", e)

    # ── ANPR ────────────────────────────────────────────────────────────

    def get_anpr_policy(self) -> dict:
        with self._lock:
            return dict(self._policy["anpr"])

    def set_anpr_policy(self, *, mode: str = None, cascade_threshold: float = None,
                        order: list = None) -> dict:
        with self._lock:
            if mode is not None:
                if mode not in VALID_MODES:
                    raise ValueError(f"mode invalide: {mode!r}")
                self._policy["anpr"]["mode"] = mode
            if cascade_threshold is not None:
                th = float(cascade_threshold)
                if not (0.0 <= th <= 1.0):
                    raise ValueError("cascade_threshold doit être entre 0 et 1")
                self._policy["anpr"]["cascade_threshold"] = th
            if order is not None:
                if not isinstance(order, list):
                    raise ValueError("order doit être une liste de noms de plugins")
                self._policy["anpr"]["order"] = [str(x) for x in order]
            self._persist()
            return dict(self._policy["anpr"])

    # ── FrameAnalyzer ───────────────────────────────────────────────────

    def get_frame_policy(self) -> dict:
        with self._lock:
            return dict(self._policy["frame_analyzer"])

    def set_frame_policy(self, *, parallel: bool = None, timeout_s: float = None) -> dict:
        with self._lock:
            if parallel is not None:
                self._policy["frame_analyzer"]["parallel"] = bool(parallel)
            if timeout_s is not None:
                t = float(timeout_s)
                if not (0.1 <= t <= 60.0):
                    raise ValueError("timeout_s doit être entre 0.1 et 60")
                self._policy["frame_analyzer"]["timeout_s"] = t
            self._persist()
            return dict(self._policy["frame_analyzer"])

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "anpr": dict(self._policy["anpr"]),
                "frame_analyzer": dict(self._policy["frame_analyzer"]),
            }


policy = PolicyStore()
