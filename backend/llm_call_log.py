"""v3.27 · Journal détaillé de tous les appels LLM/vision (Qwen via Open
WebUI) — un seul point d'écriture appelé par chaque plugin (couleur,
marque, anomalies, dédoublonnage, réglage ANPR, recherche IA). Alimente le
menu « Logs LLM » (routes/llm_logs.py, remplace l'ancien « Log ANPR ») :
chaque requête/réponse réseau, succès ou échec, avec latence — pensé pour
le debug après plusieurs pannes silencieuses (toggle désactivé, 404 muet)
qui n'avaient laissé aucune trace exploitable.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from typing import Any

from database import db

_MAX_FIELD_CHARS = 4000


def _sanitize_payload(payload: Any) -> Any:
    """Remplace les data URI d'image (couleur/marque) par un simple
    marqueur de taille — inutile au debug, coûteux à stocker."""
    try:
        p = copy.deepcopy(payload)
        messages = p.get("messages") if isinstance(p, dict) else None
        for msg in messages or []:
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        img = part.get("image_url") or {}
                        url = img.get("url", "")
                        img["url"] = f"<image {len(url)} caractères, non journalisée>"
        return p
    except Exception:
        return payload


def _truncate(value: Any) -> str | None:
    if value is None:
        return None
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(s) <= _MAX_FIELD_CHARS:
        return s
    return s[:_MAX_FIELD_CHARS] + f"… (tronqué, {len(s)} caractères au total)"


async def log_llm_call(
    *,
    source: str,
    url: str,
    model: str | None,
    request_payload: Any,
    status_code: int | None = None,
    response_body: Any = None,
    error: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """N'échoue jamais l'appel LLM appelant : toute erreur d'écriture est
    avalée, le journal de debug ne doit jamais devenir une cause de panne."""
    doc = {
        "ts": datetime.now(timezone.utc),
        "source": source,
        "url": url,
        "model": model,
        "status_code": status_code,
        "ok": error is None and (status_code is None or 200 <= status_code < 300),
        "latency_ms": latency_ms,
        "request": _truncate(_sanitize_payload(request_payload)),
        "response": _truncate(response_body),
        "error": _truncate(error),
    }
    try:
        await db.llm_call_logs.insert_one(doc)
    except Exception:
        pass
