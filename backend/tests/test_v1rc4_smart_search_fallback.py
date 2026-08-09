"""Tests v1.0-rc4 · Smart Search — fallback quand EMERGENT_LLM_KEY absente.

Vérifications :
- Sans clé → HTTPException 503 avec code SMART_SEARCH_LLM_NOT_CONFIGURED
- Message utilisateur explicite (pas "Une erreur est survenue")
- La clé n'est JAMAIS retournée dans les détails d'erreur
"""
import asyncio
import os

import pytest
from fastapi import HTTPException


def test_smart_search_returns_503_when_key_missing():
    """Absence de EMERGENT_LLM_KEY → 503 avec code normalisé.

    Exécuté dans un subprocess isolé pour garantir un env vraiment vide
    (xdist + conftest _load_env peuvent réhydrater la variable entre
    tests parallèles, ce qui rend un simple monkeypatch fragile ici).
    """
    import subprocess, sys as _sys
    result = subprocess.run(
        [_sys.executable, "-c", """
import os, asyncio, sys
# CRITIQUE : emergentintegrations appelle load_dotenv() à l'import et
# rechargerait EMERGENT_LLM_KEY depuis /app/backend/.env. On chdir hors
# de ce dossier pour simuler un container prod sans fichier .env.
os.chdir('/tmp')
os.environ.pop('EMERGENT_LLM_KEY', None)
os.environ['TESTING'] = '1'
sys.path.insert(0, '/app/backend')
# Restore MONGO_URL/DB_NAME depuis .env pour que motor puisse s'initialiser,
# SAUF EMERGENT_LLM_KEY (celui-là on veut vraiment absent).
for line in open('/app/backend/.env').read().splitlines():
    if line and not line.startswith('#') and '=' in line:
        k, _, v = line.partition('=')
        k, v = k.strip(), v.strip().strip('\"')
        if k != 'EMERGENT_LLM_KEY':
            os.environ.setdefault(k, v)
from fastapi import HTTPException
from routes.smart_search import _parse_query_llm
# Après import, re-vérifier que emergentintegrations n'a pas ré-injecté la clé
os.environ.pop('EMERGENT_LLM_KEY', None)

async def go():
    try:
        await _parse_query_llm('toyota rouge')
        print('FAIL: no exception')
        sys.exit(1)
    except HTTPException as e:
        d = e.detail if isinstance(e.detail, dict) else {}
        if e.status_code != 503: print(f'FAIL: status={e.status_code}'); sys.exit(2)
        if d.get('code') != 'SMART_SEARCH_LLM_NOT_CONFIGURED': print(f'FAIL: code={d.get(\"code\")}'); sys.exit(3)
        if 'EMERGENT_LLM_KEY' not in d.get('message', ''): print('FAIL: no key in message'); sys.exit(4)
        if 'Une erreur est survenue' in d.get('message', ''): print('FAIL: generic message'); sys.exit(5)
        print('OK')

asyncio.run(go())
"""],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr[-500:]}"
    assert "OK" in result.stdout


def test_vehicles_smart_search_returns_503_when_key_missing(monkeypatch):
    """Le second endpoint /api/vehicles/smart-search suit la même politique."""
    monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)

    from fastapi import HTTPException as HTTPEx
    # Import du code pour couvrir l'endpoint (test statique sur le pattern)
    from routes import vehicles as vehicles_mod
    # Le fichier contient bien le nouveau code d'erreur normalisé
    with open(vehicles_mod.__file__, "r") as f:
        src = f.read()
    assert 'SMART_SEARCH_LLM_NOT_CONFIGURED' in src
    assert 'status_code=503' in src
    _ = HTTPEx  # noqa (import kept for reference)


def test_llm_key_never_in_error_detail():
    """Anti-régression : jamais de fuite de la clé dans les payloads d'erreur."""
    os.environ["EMERGENT_LLM_KEY"] = "sk-super-secret-key-abc123-DO-NOT-LEAK"
    try:
        async def call():
            from routes.smart_search import _parse_query_llm
            return await _parse_query_llm("dummy query")

        # On s'attend à un 502 (clé invalide côté LLM) — la clé ne doit pas fuiter
        with pytest.raises(HTTPException) as exc:
            asyncio.run(call())
        detail_str = str(exc.value.detail)
        assert "sk-super-secret-key-abc123" not in detail_str, \
            "la clé LLM ne doit JAMAIS apparaître dans le detail d'erreur"
    finally:
        os.environ.pop("EMERGENT_LLM_KEY", None)


def test_env_example_documents_the_key():
    """Doc & config production : la clé doit être documentée dans .env.example."""
    env_example = "/app/deploy-app/.env.example"
    if not os.path.exists(env_example):
        pytest.skip("deploy-app/.env.example absent")
    with open(env_example, "r") as f:
        content = f.read()
    assert "EMERGENT_LLM_KEY" in content, ".env.example doit documenter EMERGENT_LLM_KEY"
    assert "SECRÈTE" in content or "SECRET" in content or "BACKEND ONLY" in content, \
        "la doc doit indiquer que la clé est secrète / backend only"


def test_compose_passes_key_to_backend():
    """docker-compose.yml doit injecter EMERGENT_LLM_KEY dans le container backend."""
    compose = "/app/deploy-app/docker-compose.yml"
    if not os.path.exists(compose):
        pytest.skip("deploy-app/docker-compose.yml absent")
    with open(compose, "r") as f:
        content = f.read()
    assert "EMERGENT_LLM_KEY" in content, \
        "docker-compose.yml doit passer EMERGENT_LLM_KEY au backend"
    # Doit être dans la section backend, pas frontend (backend-only)
    # Simple check : la variable apparaît AVANT la section frontend
    backend_idx = content.find("mgvms-backend")
    frontend_idx = content.find("mgvms-frontend")
    key_idx = content.find("EMERGENT_LLM_KEY:")
    if backend_idx > 0 and frontend_idx > 0:
        assert backend_idx < key_idx < frontend_idx, \
            "EMERGENT_LLM_KEY doit être injectée dans le service backend uniquement"
