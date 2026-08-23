"""Sprint Sécurité — middleware en-têtes OWASP + rate limiting léger en mémoire.

Note prod: le rate-limit en mémoire suppose un process unique. En production
multi-instances, déporter vers Redis (voir /deploy). Ici (process unique), suffisant.

En mode test (env `TESTING=1`), le rate-limit est complètement bypassé afin
d'éviter les faux positifs (429) durant les campagnes pytest parallèles. Les
en-têtes OWASP restent appliqués pour continuer à couvrir leur vérification.

v3.4 · ASGI pur, PAS BaseHTTPMiddleware : `call_next()` bufferise/rewrap
chaque réponse, ce qui casse le support natif des requêtes Range (206
Partial Content) de `FileResponse` — confirmé en prod sur
`/api/recordings/{id}/media` (vidéos d'événements) : le navigateur envoyait
bien un header `Range`, mais recevait systématiquement un 200 avec le
fichier entier au lieu d'un 206 partiel, forçant des re-téléchargements
complets répétés. Une réécriture ASGI directe (n'interceptant que
`http.response.start` pour les en-têtes, jamais le corps) n'a pas ce
problème.
"""
import os
import time
from collections import defaultdict, deque

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse


def _testing_mode() -> bool:
    return os.environ.get("TESTING", "").lower() in ("1", "true", "yes", "on")

# Limites par IP : (max requêtes, fenêtre secondes) sur chemins sensibles
SENSITIVE_LIMITS = {
    "/api/auth/login": (30, 60),
    "/api/auth/forgot-password": (5, 300),
    "/api/auth/reset-password": (10, 300),
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "1; mode=block",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}

_hits = defaultdict(deque)  # key "ip:path" -> deque[timestamps]


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        limit = SENSITIVE_LIMITS.get(path)
        if limit and scope.get("method") == "POST" and not _testing_mode():
            max_req, window = limit
            raw_headers = dict(scope.get("headers") or [])
            fwd = raw_headers.get(b"x-forwarded-for")
            client = scope.get("client")
            ip = fwd.decode().split(",")[0].strip() if fwd else (client[0] if client else "unknown")
            key = f"{ip}:{path}"
            now = time.time()
            dq = _hits[key]
            while dq and now - dq[0] > window:
                dq.popleft()
            if len(dq) >= max_req:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Trop de requêtes. Réessayez dans quelques instants."},
                    headers={"Retry-After": str(window), **SECURITY_HEADERS},
                )
                return await response(scope, receive, send)
            dq.append(now)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for k, v in SECURITY_HEADERS.items():
                    if k not in headers:
                        headers.append(k, v)
            await send(message)

        await self.app(scope, receive, send_wrapper)
