"""Sprint Sécurité — middleware en-têtes OWASP + rate limiting léger en mémoire.

Note prod: le rate-limit en mémoire suppose un process unique. En production
multi-instances, déporter vers Redis (voir /deploy). Ici (process unique), suffisant.
"""
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

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


def _client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        limit = SENSITIVE_LIMITS.get(path)
        if limit and request.method == "POST":
            max_req, window = limit
            key = f"{_client_ip(request)}:{path}"
            now = time.time()
            dq = _hits[key]
            while dq and now - dq[0] > window:
                dq.popleft()
            if len(dq) >= max_req:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Trop de requêtes. Réessayez dans quelques instants."},
                    headers={"Retry-After": str(window), **SECURITY_HEADERS},
                )
            dq.append(now)

        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response
