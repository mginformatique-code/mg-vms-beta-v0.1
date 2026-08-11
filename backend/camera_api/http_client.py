"""Camera API · Client HTTP mutualisé.

    - httpx.AsyncClient avec `verify` PER-CAMERA (jamais de désactivation globale)
    - Timeouts explicites (connect / read / overall)
    - Redaction des credentials dans les logs (URLs RTSP/HTTP + query token)
    - Retry léger sur 5xx transitoires (1 seule fois)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger("camera_api.http")

_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 10.0
_TOTAL_TIMEOUT = 15.0
_CRED_RE = re.compile(r"(://[^:@/]+):([^@/]+)@", re.IGNORECASE)
_TOKEN_RE = re.compile(r"([?&]token=)([^&\s]+)", re.IGNORECASE)


def redact_url(url: str) -> str:
    """Masque les credentials et tokens dans une URL (logs)."""
    if not url:
        return url
    url = _CRED_RE.sub(r"\1:******@", url)
    url = _TOKEN_RE.sub(r"\1******", url)
    return url


def make_client(*, base_url: str, verify_ssl: bool = True,
                 connect_timeout: float = _CONNECT_TIMEOUT,
                 read_timeout: float = _READ_TIMEOUT,
                 total_timeout: float = _TOTAL_TIMEOUT) -> httpx.AsyncClient:
    """Crée un client HTTP configuré pour UNE caméra.

    - `verify_ssl=False` : autorise les certificats self-signed (LAN uniquement).
      **Ne modifie PAS** la vérification SSL globale du process.
    - Timeouts séparés : évite tout blocage indéfini.
    """
    return httpx.AsyncClient(
        base_url=base_url,
        verify=verify_ssl,
        timeout=httpx.Timeout(total_timeout, connect=connect_timeout, read=read_timeout),
        follow_redirects=True,
        headers={"User-Agent": "MG-VMS/2.1 (camera-api)"},
    )


async def request_with_retry(client: httpx.AsyncClient, method: str, url: str,
                              *, json: Any = None, params: Any = None,
                              data: Any = None) -> httpx.Response:
    """Requête avec 1 retry sur 5xx transitoire (500-504 sauf 501). Log redact."""
    import ssl
    for attempt in (1, 2):
        try:
            r = await client.request(method, url, json=json, params=params, data=data)
        except httpx.ConnectError as e:
            # Inclut ssl.SSLError (SNI unrecognized name, cert refusé, etc.)
            raise ConnectionError(f"connect: {e}") from e
        except httpx.TimeoutException as e:
            raise TimeoutError(f"timeout: {e}") from e
        except ssl.SSLError as e:
            raise ConnectionError(f"tls: {e}") from e
        except httpx.TransportError as e:
            # Filet de sécurité (RemoteProtocolError, RemoteProtocolError, etc.)
            raise ConnectionError(f"transport: {e}") from e
        if r.status_code in (500, 502, 503, 504) and attempt == 1:
            logger.warning("camera_api HTTP %s %s → %d (retry)", method,
                           redact_url(str(r.url)), r.status_code)
            continue
        return r
    return r  # type: ignore[return-value]
