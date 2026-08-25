from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from threading import Lock
from uuid import uuid4

import logging

try:
    import redis
except ImportError:
    redis = None
try:
    import structlog
except ImportError:
    structlog = None
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.observability import HTTP_LATENCY, HTTP_REQUESTS, SECURITY_EVENTS


log = structlog.get_logger(__name__) if structlog else logging.getLogger(__name__)


def _default_csp() -> str:
    """Content-Security-Policy for non-documentation responses.

    `connect-src` used to hard-code http://localhost:8000, which is wrong on any
    deployment. It is now derived from the configured origins.
    """
    connect = ["'self'", *settings.cors_origin_list]
    if settings.web_base_url:
        connect.append(settings.web_base_url)
    if settings.public_base_url:
        connect.append(settings.public_base_url)
    if not settings.is_production:
        connect += ["ws:", "wss:"]
    else:
        connect.append("wss:")
    unique = list(dict.fromkeys(connect))
    return (
        "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        f"connect-src {' '.join(unique)}; "
        "script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; worker-src 'self' blob:"
    )


class EnterpriseMiddleware(BaseHTTPMiddleware):
    """Request IDs, security headers, HTTPS enforcement, metrics and fixed-window limiting."""

    def __init__(self, app):
        super().__init__(app)
        self._redis = None
        self._redis_failed = False
        self._local_windows: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
        self._lock = Lock()

    @staticmethod
    def _fingerprint(value: str) -> str:
        """Stable across processes and restarts, unlike the built-in hash()."""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    def _rate_limit_key(self, request: Request) -> str:
        client_ip = request.client.host if request.client else "unknown"
        if settings.trust_forwarded_for:
            forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            client_ip = forwarded or client_ip
        credential = request.headers.get("x-api-key") or request.headers.get("authorization") or ""
        identity = self._fingerprint(credential) if credential else f"ip:{client_ip}"
        # The quota is per caller, not per caller-and-path: a per-path key silently
        # multiplied the effective limit by the number of endpoints.
        return f"ct:rl:{identity}"

    def _redis_client(self):
        if redis is None:
            self._redis_failed = True
            return None
        if self._redis is None and not self._redis_failed:
            try:
                self._redis = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.25, socket_timeout=0.25)
                self._redis.ping()
            except Exception:
                self._redis_failed = True
                self._redis = None
        return self._redis

    def _allowed(self, request: Request) -> tuple[bool, int]:
        if not settings.rate_limit_enabled:
            return True, settings.rate_limit_requests
        if request.url.path in {"/health", "/health/live", "/health/ready", "/ready", "/metrics"}:
            return True, settings.rate_limit_requests
        key = self._rate_limit_key(request)
        client = self._redis_client()
        if client:
            try:
                count = int(client.incr(key))
                if count == 1:
                    client.expire(key, settings.rate_limit_window_seconds)
                return count <= settings.rate_limit_requests, max(0, settings.rate_limit_requests - count)
            except Exception:
                if not settings.rate_limit_fail_open:
                    return False, 0
        now = time.monotonic()
        with self._lock:
            count, expires = self._local_windows[key]
            if now >= expires:
                count, expires = 0, now + settings.rate_limit_window_seconds
            count += 1
            self._local_windows[key] = (count, expires)
            return count <= settings.rate_limit_requests, max(0, settings.rate_limit_requests - count)

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()

        health_path = request.url.path in {"/health", "/health/live", "/health/ready", "/ready", "/metrics"}
        if settings.force_https and not health_path and request.url.scheme != "https" and request.headers.get("x-forwarded-proto", "http") != "https":
            target = request.url.replace(scheme="https")
            return RedirectResponse(str(target), status_code=307)

        allowed, remaining = self._allowed(request)
        if not allowed:
            SECURITY_EVENTS.labels("rate_limit_exceeded").inc()
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "request_id": request_id},
                headers={"Retry-After": str(settings.rate_limit_window_seconds)},
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                if structlog:
                    log.exception("request_failed", request_id=request_id, method=request.method, path=request.url.path)
                else:
                    log.exception("request_failed request_id=%s method=%s path=%s", request_id, request.method, request.url.path)
                # Starlette's own 500 is produced above the CORS middleware, so a
                # browser sees an opaque network failure instead of the error. Answer
                # from inside the stack: the response then carries CORS headers and a
                # request id the operator can grep for in the logs.
                SECURITY_EVENTS.labels("unhandled_exception").inc()
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "Internal server error", "request_id": request_id},
                )

        elapsed = time.perf_counter() - started
        path_template = request.scope.get("route").path if request.scope.get("route") else request.url.path
        HTTP_REQUESTS.labels(request.method, path_template, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, path_template).observe(elapsed)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        if settings.security_headers_enabled:
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
            if request.url.path.startswith(("/docs", "/redoc")):
                response.headers["Content-Security-Policy"] = (
                    "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
                    "connect-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; font-src 'self' https://cdn.jsdelivr.net"
                )
            else:
                response.headers["Content-Security-Policy"] = _default_csp()
            if settings.force_https:
                response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        if structlog:
            log.info(
                "request_complete",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round(elapsed * 1000, 2),
            )
        else:
            log.info(
                "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
                request_id, request.method, request.url.path, response.status_code, elapsed * 1000,
            )
        return response
