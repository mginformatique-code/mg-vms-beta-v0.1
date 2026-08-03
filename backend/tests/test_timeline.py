"""Tests P5 · Timeline avancée + multi-ANPR."""
import httpx


BASE = "http://localhost:8001"
ADMIN = {"email": "admin@mg-vms.com", "password": "Admin@2026"}


def _token():
    r = httpx.post(f"{BASE}/api/auth/login", json=ADMIN, timeout=10)
    r.raise_for_status()
    d = r.json()
    return d.get("access_token") or d.get("token")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


def test_timeline_returns_all_layers_by_default():
    r = httpx.get(f"{BASE}/api/timeline?limit_per_layer=50", headers=_auth(), timeout=30)
    assert r.status_code == 200
    d = r.json()
    for k in ("since", "until", "counts", "total", "events", "alerts", "plates", "recordings"):
        assert k in d, f"Champ '{k}' manquant"
    assert d["total"] == sum(d["counts"].values())


def test_timeline_filter_by_layer():
    r = httpx.get(f"{BASE}/api/timeline?layers=plates",
                   headers=_auth(), timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert "plates" in d
    assert d.get("events") is None or d.get("events") == []
    # counts ne contient que plates
    assert set(d["counts"].keys()) == {"plates"}


def test_timeline_filter_by_camera():
    """`camera_ids` doit restreindre le scope."""
    r = httpx.get(f"{BASE}/api/timeline?camera_ids=demo-cam-001",
                   headers=_auth(), timeout=15)
    assert r.status_code == 200
    d = r.json()
    # Tous les items retournés doivent appartenir à demo-cam-001
    for layer in ("events", "alerts", "plates", "recordings"):
        for item in d.get(layer, []) or []:
            assert item["camera_id"] == "demo-cam-001", (
                f"item {layer} avec camera_id={item['camera_id']}"
            )


def test_timeline_items_include_engine_for_plates():
    """Chaque plate doit exposer le champ `engine` (traçabilité multi-moteurs)."""
    r = httpx.get(f"{BASE}/api/timeline?layers=plates",
                   headers=_auth(), timeout=15)
    d = r.json()
    plates = d.get("plates") or []
    if not plates:
        return
    for p in plates[:20]:
        assert "engine" in p, f"plate sans engine : {p}"


def test_timeline_time_range_absolute():
    """Une fenêtre courte doit filtrer les résultats."""
    from datetime import datetime, timezone, timedelta
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    until = datetime.now(timezone.utc).isoformat()
    r = httpx.get(f"{BASE}/api/timeline",
                   params={"since": since, "until": until, "layers": "events"},
                   headers=_auth(), timeout=15)
    assert r.status_code == 200
    d = r.json()
    # Tous les timestamps events doivent être dans la fenêtre
    for ev in d.get("events", []):
        assert since <= ev["timestamp"] <= until, f"event hors fenêtre : {ev['timestamp']}"
