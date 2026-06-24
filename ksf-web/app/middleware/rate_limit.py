"""Rate limiting middleware (token bucket in-memory par IP).

Limites par défaut :
- GET : 100 req/min
- POST non-sensibles : 30 req/min
- POST destructifs (install/remove/restore/restart/ban) : 5 req/5min
- SSE : 5 connexions concurrentes par IP

Exempt : /health, /static/*, /api/notifications/unread-count.

Headers de réponse : X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset.

NB : le state est in-memory (dict). Au restart du conteneur, les compteurs
sont réinitialisés. Acceptable pour single-user. Pour multi-instance, passer
à Redis.

Sécurité :
- Le peer direct doit être un proxy de confiance (configurable via
  `TRUSTED_PROXY_IPS`, défaut : loopback uniquement = Traefik sur la même
  machine). Sans cela, l'attaquant peut injecter un X-Forwarded-For
  arbitraire et bypass le rate-limit par IP.
- Les buckets sont évincés périodiquement pour éviter un memory leak
  sur rotation d'IPs (e.g. derrière Cloudflare).
"""
import asyncio
import logging
import os
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("ksf-web.rate-limit")

# (max_tokens, refill_per_sec)
LIMITS = {
    "GET": (100, 100 / 60.0),       # 100 par minute
    "POST_SAFE": (30, 30 / 60.0),   # 30 par minute
    "POST_DESTRUCTIVE": (5, 5 / 300.0),  # 5 par 5 minutes
    "SSE": (5, 5 / 60.0),           # 5 par minute
}

DESTRUCTIVE_PATTERNS = (
    "/install", "/remove", "/restore", "/restart", "/ban",
    "/toggle", "/apply", "/prune", "/flush", "/disable",
    "/rebuild", "/enable", "/unban", "/revoke",
    "/regenerate", "/rotate",
)
SSE_PATTERNS = ("/stream", "/events")
EXEMPT_PATTERNS = ("/health", "/static/", "/api/notifications/unread-count", "/favicon")

# IPs de proxies de confiance (peuple X-Forwarded-For / X-Real-IP).
# Défaut : loopback uniquement, ce qui correspond à Traefik sur la même
# machine. Pour Cloudflare/Traefik distant, ajouter les CIDR dans
# `KSF_TRUSTED_PROXY_IPS` (séparés par virgule).
_TRUSTED_PROXY_IPS_STR = os.environ.get("KSF_TRUSTED_PROXY_IPS", "127.0.0.1,::1")


def _parse_trusted_ips() -> set[str]:
    out: set[str] = set()
    for s in _TRUSTED_PROXY_IPS_STR.split(","):
        s = s.strip()
        if s:
            out.add(s)
    return out


_TRUSTED_PROXIES = _parse_trusted_ips()
_BUCKETS_MAX_SIZE = 10000  # cap mémoire
_buckets: "OrderedDict[str, dict[str, tuple[float, float]]]" = OrderedDict()
_buckets_lock = asyncio.Lock()


def _bucket_key(method: str, path: str) -> str:
    if any(p in path for p in SSE_PATTERNS):
        return "SSE"
    if method == "GET":
        return "GET"
    if any(p in path for p in DESTRUCTIVE_PATTERNS):
        return "POST_DESTRUCTIVE"
    return "POST_SAFE"


def _client_ip(request) -> str:
    """Détermine l'IP réelle du client, en ne faisant confiance à XFF
    que si le peer direct est un proxy de confiance.

    Bug-fix : l'expression précédente `XFF or XRI or client.host if client
    else "unknown"` se parse comme `(... or client.host) if client else
    "unknown"`, faisant tomber tous les clients sans peer dans le bucket
    "unknown" commun.
    """
    peer = request.client.host if request.client else None
    if peer and peer in _TRUSTED_PROXIES:
        xff = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
        if xff:
            # XFF peut être "client, proxy1, proxy2" : prendre la première
            return xff.split(",")[0].strip()
    return peer or "unknown"


def _take_token(ip: str, key: str) -> tuple[bool, int, float, int]:
    """Atomique (pas de lock Python) — suffisant pour limiter grossièrement.

    Renvoie (allowed, remaining, reset_sec, limit).
    Met à jour le LRU OrderedDict pour l'éviction.
    """
    max_tokens, refill = LIMITS[key]
    now = time.time()
    bucket = _buckets.get(ip)
    if bucket is None:
        bucket = {}
        _buckets[ip] = bucket
    else:
        _buckets.move_to_end(ip)  # LRU touch
    tokens, last = bucket.get(key, (max_tokens, now))
    elapsed = max(0.0, now - last)
    tokens = min(max_tokens, tokens + elapsed * refill)
    if tokens >= 1.0:
        tokens -= 1.0
        bucket[key] = (tokens, now)
        reset = (max_tokens - tokens) / refill if refill > 0 else 0
        return True, int(tokens), reset, max_tokens
    else:
        bucket[key] = (tokens, now)
        reset = (1.0 - tokens) / refill if refill > 0 else 1
        return False, 0, reset, max_tokens


def _evict_buckets_if_needed() -> None:
    """Évince les buckets les plus anciens si on dépasse _BUCKETS_MAX_SIZE."""
    while len(_buckets) > _BUCKETS_MAX_SIZE:
        _buckets.popitem(last=False)  # FIFO : supprime le plus ancien


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in EXEMPT_PATTERNS):
            return await call_next(request)

        ip = _client_ip(request)
        key = _bucket_key(request.method, path)
        allowed, remaining, reset, limit = _take_token(ip, key)
        _evict_buckets_if_needed()

        if not allowed:
            logger.warning("Rate limit: %s %s from %s (key=%s, reset=%.1fs)",
                           request.method, path, ip, key, reset)
            return JSONResponse(
                {"detail": "Trop de requêtes. Réessayez dans quelques secondes."},
                status_code=429,
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(reset)),
                    "Retry-After": str(int(reset) + 1),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(reset))
        return response
