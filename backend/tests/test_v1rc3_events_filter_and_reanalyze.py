"""v1.0-rc3 · FEATURE FREEZE · Fix qos_alert + Bouton Analyser OCR

Deux corrections mesurables :

  A) `/api/events` sans filtre `type` exclut désormais `qos_alert`
     (rétrocompat : `?type=qos_alert` reste accessible)
  B) `POST /api/events/{id}/reanalyze` relance l'OCR sur la miniature
"""
from __future__ import annotations

import os
import base64
import asyncio
import pytest


os.environ["TESTING"] = "1"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestEventsExcludeQosAlert:
    """Preuve : la vue événements ne mélange plus alertes techniques et détections."""

    def test_default_query_excludes_qos_alert(self):
        """Sans param `type`, le query mongo doit contenir `$nin` avec qos_alert."""
        src = open("/app/backend/routers.py", encoding="utf-8").read()
        # Preuve statique : le fix est bien présent
        assert '"$nin": ["qos_alert"]' in src
        assert "n'ont rien à faire mélangées" in src

    def test_explicit_type_still_works(self):
        """Rétrocompat : `?type=qos_alert` doit rester accessible."""
        src = open("/app/backend/routers.py", encoding="utf-8").read()
        # Le if type: passe dans le path explicite (pas d'exclusion)
        idx_if = src.find("if type:")
        idx_else = src.find("else:", idx_if)
        idx_excl = src.find('"$nin": ["qos_alert"]', idx_else)
        # L'exclusion est bien dans le else (pas dans le if type)
        assert idx_if < idx_else < idx_excl


class TestReanalyzeEndpoint:
    """L'endpoint POST /events/{id}/reanalyze est enregistré et retourne un JSON structuré."""

    def test_endpoint_registered(self):
        from server import app
        # Cherche le POST sur cette route
        found = False
        for r in app.routes:
            if getattr(r, "path", "") == "/api/events/{event_id}/reanalyze":
                methods = getattr(r, "methods", set()) or set()
                if "POST" in methods:
                    found = True
                    break
        assert found, "POST /api/events/{event_id}/reanalyze non enregistré"

    def test_404_on_unknown_event(self, monkeypatch):
        """Event inconnu → 404 propre."""
        from fastapi import HTTPException
        import routers as R

        class FakeCollection:
            async def find_one(self, *a, **k):
                return None

        class FakeDB:
            events = FakeCollection()

        monkeypatch.setattr(R, "db", FakeDB())
        with pytest.raises(HTTPException) as exc:
            _run(R.reanalyze_event("nope-id", {"role": "admin"}))
        assert exc.value.status_code == 404

    def test_400_if_no_thumbnail(self, monkeypatch):
        """Event sans thumbnail → 400."""
        from fastapi import HTTPException
        import routers as R

        class FakeCollection:
            async def find_one(self, *a, **k):
                return {"id": "e1", "timestamp": "2026-08-07T00:00:00Z"}

        class FakeDB:
            events = FakeCollection()

        monkeypatch.setattr(R, "db", FakeDB())
        with pytest.raises(HTTPException) as exc:
            _run(R.reanalyze_event("e1", {"role": "admin"}))
        assert exc.value.status_code == 400
        assert "miniature" in str(exc.value.detail).lower()

    def test_reanalyze_flow_when_no_plate_found(self, monkeypatch):
        """Cas nominal : image lisible mais aucune plaque détectée."""
        import routers as R

        # Fake image bytes : 1×1 JPEG minimal
        fake_jpeg_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
                          "CAAAAAA6fptVAAAACklEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII=")
        thumb = f"data:image/png;base64,{fake_jpeg_b64}"

        class FakeCollection:
            async def find_one(self, *a, **k):
                return {"id": "e1", "thumbnail": thumb,
                        "timestamp": "2026-08-07T00:00:00Z"}

            async def update_one(self, *a, **k):
                return type("R", (), {"modified_count": 1})()

        class FakeDB:
            events = FakeCollection()

        # Mock ai_engine.analyze_image_local
        import ai_engine as ae
        monkeypatch.setattr(ae, "analyze_image_local",
                             lambda b: {"plate": "", "confidence": 0.0,
                                        "vehicle_type": "Inconnu",
                                        "vehicle_color": ""})
        monkeypatch.setattr(R, "db", FakeDB())

        result = _run(R.reanalyze_event("e1", {"role": "admin"}))
        assert result["ok"] is True
        assert result["plate"] is None
        assert "Aucune plaque" in result["message"]

    def test_reanalyze_flow_when_plate_found(self, monkeypatch):
        """Cas nominal : plaque détectée → retour + persist update."""
        import routers as R

        fake_jpeg_b64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
                          "CAAAAAA6fptVAAAACklEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII=")
        thumb = f"data:image/png;base64,{fake_jpeg_b64}"
        writes: list = []

        class FakeCollection:
            async def find_one(self, *a, **k):
                return {"id": "e1", "thumbnail": thumb, "timestamp": "..."}

            async def update_one(self, filt, update, *a, **k):
                writes.append((filt, update))
                return type("R", (), {"modified_count": 1})()

        class FakeDB:
            events = FakeCollection()

        import ai_engine as ae
        monkeypatch.setattr(ae, "analyze_image_local",
                             lambda b: {"plate": "AB-123-CD", "confidence": 0.87,
                                        "vehicle_type": "Voiture", "vehicle_color": "Bleu"})
        monkeypatch.setattr(R, "db", FakeDB())

        result = _run(R.reanalyze_event("e1", {"role": "admin"}))
        assert result["ok"] is True
        assert result["plate"] == "AB-123-CD"
        assert result["confidence"] == 0.87
        # Doit persister avec les 4 champs reanalyzed_* + `plate` + `confidence`
        assert len(writes) == 1
        _, upd = writes[0]
        setclause = upd["$set"]
        assert "reanalyzed_at" in setclause
        assert setclause["reanalyzed_plate"] == "AB-123-CD"
        assert setclause["reanalyzed_confidence"] == 0.87
        assert setclause["plate"] == "AB-123-CD"


class TestFrontendReanalyzeButton:
    """Le bouton "Analyser OCR" est présent dans EventViewer.jsx."""

    @pytest.fixture(scope="class")
    def content(self):
        return open("/app/frontend/src/components/EventViewer.jsx",
                     encoding="utf-8").read()

    def test_button_only_shown_without_plate(self, content):
        """Condition d'affichage : kind=event ET !plate ET thumbnail présent."""
        assert 'kind === "event" && !item.plate && !ocrResult?.plate && item.thumbnail' in content

    def test_calls_reanalyze_endpoint(self, content):
        assert "api.post(`/events/${item.id}/reanalyze`)" in content

    def test_button_uses_testid(self, content):
        assert 'data-testid="viewer-reanalyze-btn"' in content


class TestNoRegression:
    def test_events_recording_still_registered(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/events/{event_id}/recording" in paths
        assert "/api/events" in paths
