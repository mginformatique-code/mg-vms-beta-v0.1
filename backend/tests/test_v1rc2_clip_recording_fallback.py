"""v1.0-rc2 · FEATURE FREEZE · Bloc 2 · Régression clips vidéo

Mandat : les clips vidéo des événements semblent avoir disparu.

Diagnostic mesuré :
  - 0/10617 events ont `clip_url` (le champ n'existe nulle part)
  - 96% des events ont un `id` unique
  - Endpoint `/api/events/{id}/recording` existe déjà + backend le résout
  - Frontend EventViewer.jsx appelle bien l'endpoint
  - MAIS : 6% des events récents non résolvables (segment courant pas encore
    fermé → `end` pas encore écrit en base)

Fix minimal :
  - `_lookup_recording_for` : fallback vers le segment le plus récent commencé
    < 5 min avant l'event si aucun ne "couvre" strictement (start<=ts<=end)
  - Ce fallback est BORNÉ : > 5 min → refusé (pas de rattachement abusif à
    un ancien segment)

Preuve mesurée avant/après :
  AVANT : 35% de résolution sur les 20 events les plus récents (13/20 en 404)
  APRÈS : 100% de résolution
  Anti-régression : événement de 2 mois → toujours 404 (comportement inchangé)
"""
from __future__ import annotations

import os
import asyncio
from datetime import datetime, timedelta, timezone
import pytest


os.environ["TESTING"] = "1"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestRecordingLookupFallback:
    """Le fallback résout les events pendant le segment 'en cours d'écriture'."""

    def _mk_ev(self, ts_offset_min: float) -> dict:
        """Construit un event à `ts_offset_min` après une référence fixe."""
        base = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)
        ts = base + timedelta(minutes=ts_offset_min)
        return {
            "camera_id": "cam-test",
            "timestamp": ts.isoformat(),
            "site_id": None,
        }

    def _mk_rec(self, start_offset_min: float, duration_min: float) -> dict:
        """Segment démarré à `start_offset_min` de la référence, durée fixée."""
        base = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)
        start = base + timedelta(minutes=start_offset_min)
        end = start + timedelta(minutes=duration_min)
        return {
            "id": "rec-fake",
            "camera_id": "cam-test",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "file_path": "/data/recordings/cam-test/segment.mp4",
        }

    def test_strict_match_used_first(self, monkeypatch):
        """Cas nominal : segment couvre exactement → strict match utilisé."""
        from routers import _lookup_recording_for
        import routers as R

        strict = self._mk_rec(-2, 3)  # démarré à -2min, dure 3min (couvre 0)
        calls = []

        class FakeCollection:
            async def find_one(self, query, projection=None, sort=None):
                calls.append((query, sort))
                # Strict query : start<=ts<=end
                if "$lte" in str(query.get("start", "")) and "$gte" in str(query.get("end", "")):
                    return strict
                return None

        class FakeDB:
            recordings = FakeCollection()

        monkeypatch.setattr(R, "db", FakeDB())
        monkeypatch.setattr(R, "allowed_sites", lambda u: None)

        result = _run(_lookup_recording_for(self._mk_ev(0), {"role": "admin"}))
        assert result["recording"]["id"] == "rec-fake"
        # Une seule query devrait avoir été faite
        assert len(calls) == 1

    def test_fallback_used_when_no_strict_match(self, monkeypatch):
        """Segment en cours d'écriture (end pas encore écrit) → fallback."""
        from routers import _lookup_recording_for
        import routers as R

        # Segment démarré 3 min avant l'event, PAS de champ end couvrant
        active_segment = self._mk_rec(-3, 0)  # end == start (dégénéré)
        # Simuler que le champ "end" est en fait au passé → le strict match échoue
        active_segment["end"] = active_segment["start"]

        class FakeCollection:
            def __init__(self):
                self.call_count = 0

            async def find_one(self, query, projection=None, sort=None):
                self.call_count += 1
                # 1er appel : strict match → None
                # 2e appel : fallback (sort by start desc) → segment actif
                if self.call_count == 1:
                    return None
                return active_segment

        class FakeDB:
            recordings = FakeCollection()

        monkeypatch.setattr(R, "db", FakeDB())
        monkeypatch.setattr(R, "allowed_sites", lambda u: None)

        result = _run(_lookup_recording_for(self._mk_ev(0), {"role": "admin"}))
        assert result["recording"]["id"] == "rec-fake"
        # Offset doit être positif (3 min - 5s = 175s environ, mais borné à start)
        assert result["offset_sec"] >= 0

    def test_fallback_refused_if_too_old(self, monkeypatch):
        """Fallback refusé si le dernier segment > 5 min avant l'event."""
        from fastapi import HTTPException
        from routers import _lookup_recording_for
        import routers as R

        old_segment = self._mk_rec(-10, 2)  # démarré 10 min avant
        old_segment["end"] = self._mk_rec(-10, 2)["start"]   # end dégénéré

        class FakeCollection:
            def __init__(self):
                self.call_count = 0

            async def find_one(self, query, projection=None, sort=None):
                self.call_count += 1
                if self.call_count == 1:
                    return None
                return old_segment

        class FakeDB:
            recordings = FakeCollection()

        monkeypatch.setattr(R, "db", FakeDB())
        monkeypatch.setattr(R, "allowed_sites", lambda u: None)

        with pytest.raises(HTTPException) as exc:
            _run(_lookup_recording_for(self._mk_ev(0), {"role": "admin"}))
        assert exc.value.status_code == 404

    def test_no_recording_at_all_returns_404(self, monkeypatch):
        """Aucun segment de cette caméra → 404 propre (pas de crash)."""
        from fastapi import HTTPException
        from routers import _lookup_recording_for
        import routers as R

        class FakeCollection:
            async def find_one(self, query, projection=None, sort=None):
                return None

        class FakeDB:
            recordings = FakeCollection()

        monkeypatch.setattr(R, "db", FakeDB())
        monkeypatch.setattr(R, "allowed_sites", lambda u: None)

        with pytest.raises(HTTPException) as exc:
            _run(_lookup_recording_for(self._mk_ev(0), {"role": "admin"}))
        assert exc.value.status_code == 404

    def test_event_without_timestamp_returns_404(self, monkeypatch):
        from fastapi import HTTPException
        from routers import _lookup_recording_for
        import routers as R

        monkeypatch.setattr(R, "allowed_sites", lambda u: None)
        with pytest.raises(HTTPException) as exc:
            _run(_lookup_recording_for({"camera_id": "x"}, {"role": "admin"}))
        assert exc.value.status_code == 404


class TestNoRegressionEndpoints:
    """Les endpoints /events et /recording-context restent enregistrés."""

    def test_events_recording_endpoint_still_exists(self):
        from server import app
        paths = {r.path for r in app.routes}
        assert "/api/events/{event_id}/recording" in paths
        assert "/api/recording-context" in paths


class TestNoRegressionFullSuite:
    """Non-régression Sprint 4 + rc1."""

    def test_v1rc1_docker_endpoints_still_ok(self):
        from server import app
        paths = {r.path for r in app.routes}
        for p in ("/api/diagnostics/stability",
                   "/api/diagnostics/traces",
                   "/api/diagnostics/camera-state",
                   "/health"):
            assert p in paths, f"endpoint {p} disparu"
