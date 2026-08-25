from __future__ import annotations

import time
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.observability import READINESS
from app.services.migrations import migration_status
from app.services.object_storage import storage
from app.services.worker_heartbeat import active_workers


def _result(ok: bool, *, latency_ms: float | None = None, detail: str = "") -> dict[str, object]:
    payload: dict[str, object] = {"ok": ok}
    if latency_ms is not None:
        payload["latency_ms"] = round(latency_ms, 2)
    if detail:
        payload["detail"] = detail
    return payload


def _database(db: Session) -> dict[str, object]:
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        return _result(True, latency_ms=(time.perf_counter() - started) * 1000)
    except Exception as exc:
        return _result(False, latency_ms=(time.perf_counter() - started) * 1000, detail=str(exc))


def _redis() -> dict[str, object]:
    started = time.perf_counter()
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        client.ping()
        return _result(True, latency_ms=(time.perf_counter() - started) * 1000)
    except Exception as exc:
        return _result(not settings.redis_required, latency_ms=(time.perf_counter() - started) * 1000, detail=str(exc))


def _storage() -> dict[str, object]:
    started = time.perf_counter()
    try:
        storage.healthcheck()
        return _result(True, latency_ms=(time.perf_counter() - started) * 1000, detail=storage.backend)
    except Exception as exc:
        return _result(False, latency_ms=(time.perf_counter() - started) * 1000, detail=str(exc))


def _migrations() -> dict[str, object]:
    try:
        status = migration_status()
        return {"ok": bool(status["at_head"]), **status}
    except Exception as exc:
        return _result(False, detail=str(exc))


def _workers(db: Session) -> dict[str, object]:
    workers = active_workers(db)
    ok = bool(workers) or not settings.require_asset_worker
    return {
        "ok": ok,
        "required": settings.require_asset_worker,
        "active": len(workers),
        "workers": [
            {
                "worker_id": row.worker_id,
                "status": row.status,
                "version": row.version,
                "last_seen_at": row.last_seen_at,
            }
            for row in workers
        ],
    }


def _provider() -> dict[str, object]:
    if not settings.oneai_core_url:
        return {"ok": not settings.provider_health_required, "configured": False}
    started = time.perf_counter()
    try:
        headers = {"Authorization": f"Bearer {settings.oneai_core_api_key}"} if settings.oneai_core_api_key else {}
        response = httpx.get(settings.oneai_core_url.rstrip("/") + "/health", headers=headers, timeout=2.0)
        ok = response.status_code < 500
        return _result(ok, latency_ms=(time.perf_counter() - started) * 1000, detail=str(response.status_code))
    except Exception as exc:
        return _result(not settings.provider_health_required, latency_ms=(time.perf_counter() - started) * 1000, detail=str(exc))


def readiness_report(db: Session) -> tuple[bool, dict[str, object]]:
    checks = {
        "database": _database(db),
        "migrations": _migrations(),
        "redis": _redis(),
        "object_storage": _storage(),
        "asset_worker": _workers(db),
        "oneai_core": _provider(),
    }
    required = ["database", "migrations", "object_storage", "asset_worker", "oneai_core"]
    if settings.redis_required:
        required.append("redis")
    ok = all(bool(checks[name].get("ok")) for name in required)
    for name, result in checks.items():
        READINESS.labels(name).set(1 if result.get("ok") else 0)
    return ok, {
        "status": "ready" if ok else "not_ready",
        "service": "construction-twin-api",
        "version": settings.app_version,
        "environment": settings.app_env,
        "checks": checks,
    }
