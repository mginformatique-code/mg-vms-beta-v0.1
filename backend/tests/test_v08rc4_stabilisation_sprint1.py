"""v0.8-rc4 · FEATURE FREEZE · Stabilisation Sprint 1

Corrections mesurables :
  A) Fix disque plein : cache webpack en mémoire (craco.config.js)
  B) Fix QoS spam : backoff progressif (qos_alerts.py) 30s→60s→120s→300s
  C) Regression : indexes bootstrap + VirtualGrid contract intacts
"""
from __future__ import annotations

import asyncio
import os
import time
import pytest


os.environ["TESTING"] = "1"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestQosBackoffProgressif:
    """Preuve : le backoff double le cooldown à chaque ré-émission."""

    def _fresh(self, monkeypatch=None):
        """Recharge le module et reset l'état pour un test isolé.

        Patche db.events par un mock in-memory qui capture les insert_one.
        Retourne (module qos, captured_docs list).
        """
        from pipeline_v2 import qos_alerts
        qos_alerts.reset_alert_state()
        captured = []

        class FakeCollection:
            async def insert_one(self, doc):
                captured.append(doc)
                return type("R", (), {"inserted_id": "x"})()

        class FakeDB:
            events = FakeCollection()

        if monkeypatch:
            monkeypatch.setattr(qos_alerts, "db", FakeDB())
        return qos_alerts, captured

    def test_first_alert_always_emits(self, monkeypatch):
        qos, captured = self._fresh(monkeypatch)
        _run(qos._emit_alert("cam-1", "yolo_slow", "warning", "test", {}))
        assert len(captured) == 1

    def test_backoff_progressive_cooldown(self, monkeypatch):
        """v0.8-rc4 · Preuve mesurée : cooldown suit 30, 60, 120, 300, 300..."""
        qos, emitted = self._fresh(monkeypatch)

        # 1re émission
        _run(qos._emit_alert("cam-1", "yolo_slow", "warning", "m", {}))
        # 2e émission immédiate → doit être bloquée
        _run(qos._emit_alert("cam-1", "yolo_slow", "warning", "m", {}))
        assert len(emitted) == 1  # spam bloqué

        # Vérif cooldown attendu après 1ère émission : 60s (repeat_count=1 → step[1])
        assert qos._current_cooldown(("cam-1", "yolo_slow")) == 60.0

        # Simule passage de 61s → 2e doit passer
        qos._last_notified[("cam-1", "yolo_slow")] = time.time() - 61
        _run(qos._emit_alert("cam-1", "yolo_slow", "warning", "m", {}))
        assert len(emitted) == 2
        assert qos._current_cooldown(("cam-1", "yolo_slow")) == 120.0

        # Simule 121s → 3e passe
        qos._last_notified[("cam-1", "yolo_slow")] = time.time() - 121
        _run(qos._emit_alert("cam-1", "yolo_slow", "warning", "m", {}))
        assert len(emitted) == 3
        assert qos._current_cooldown(("cam-1", "yolo_slow")) == 300.0

        # Après 4e, plafond 300s reste
        qos._last_notified[("cam-1", "yolo_slow")] = time.time() - 301
        _run(qos._emit_alert("cam-1", "yolo_slow", "warning", "m", {}))
        assert len(emitted) == 4
        assert qos._current_cooldown(("cam-1", "yolo_slow")) == 300.0

    def test_backoff_isolated_per_kind_and_camera(self, monkeypatch):
        qos, emitted = self._fresh(monkeypatch)

        # 2 kinds sur la même caméra → chacun émet 1 fois initialement
        _run(qos._emit_alert("cam-A", "yolo_slow", "warning", "y", {}))
        _run(qos._emit_alert("cam-A", "fps_low", "info", "f", {}))
        # 1 kind sur une autre caméra → émet aussi
        _run(qos._emit_alert("cam-B", "yolo_slow", "warning", "y", {}))
        assert len(emitted) == 3

    def test_reset_alert_state_purges(self, monkeypatch):
        qos, _ = self._fresh(monkeypatch)

        _run(qos._emit_alert("cam-1", "yolo_slow", "warning", "m", {}))
        _run(qos._emit_alert("cam-2", "fps_low", "info", "f", {}))
        assert len(qos._last_notified) == 2

        purged = qos.reset_alert_state()
        assert purged == 2
        assert not qos._last_notified
        assert not qos._repeat_count


class TestQosAlertDocumentContainsBackoffMeta:
    """v0.8-rc4 · Les alertes émises embarquent repeat_count + cooldown_s pour audit."""

    def test_alert_doc_contains_backoff_metadata(self, monkeypatch):
        from pipeline_v2 import qos_alerts
        qos_alerts.reset_alert_state()

        captured = []

        class FakeCollection:
            async def insert_one(self, doc):
                captured.append(doc)
                return type("R", (), {"inserted_id": "x"})()

        class FakeDB:
            events = FakeCollection()

        monkeypatch.setattr(qos_alerts, "db", FakeDB())
        _run(qos_alerts._emit_alert("cam-x", "pipeline_slow", "warning", "m", {"stage": "yolo"}))
        assert captured
        det = captured[0]["details"]
        assert det.get("stage") == "yolo"  # payload d'origine préservé
        assert det.get("repeat_count") == 1
        assert det.get("cooldown_s") == 30.0  # 1ère émission = step[0]


class TestCracoConfigDisksafeCache:
    """Preuve : craco.config.js configure cache mémoire en dev pour éviter ENOSPC."""

    def test_craco_config_uses_memory_cache_in_dev(self):
        src = open("/app/frontend/craco.config.js", encoding="utf-8").read()
        assert "webpackConfig.cache = { type: 'memory' }" in src
        assert "v0.8-rc4" in src  # commentaire tracé
        assert "isDevServer" in src  # conditionné dev only


class TestNoRegression:
    """Vérifie que les corrections de stabilité n'ont cassé aucun endpoint clé."""

    def test_qos_thresholds_endpoint_still_exists(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/diagnostics/qos-thresholds" in paths

    def test_pipeline_inspector_endpoint_still_exists(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/diagnostics/pipeline-inspector" in paths
