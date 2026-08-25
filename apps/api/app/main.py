from __future__ import annotations

from contextlib import asynccontextmanager

import logging

try:
    import structlog
except ImportError:  # minimal test/runtime fallback
    structlog = None
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes.bim import router as bim_router
from app.api.routes.demo import router as demo_router
from app.api.routes.enterprise import router as enterprise_router
from app.api.routes.projects import router as projects_router
from app.api.routes.read import router as read_router
from app.api.routes.v03 import router as v03_router
from app.api.routes.v04 import router as v04_router
from app.api.routes.v05 import router as v05_router
from app.api.routes.v06 import router as v06_router
from app.core.config import settings
from app.core.middleware import EnterpriseMiddleware
from app.core.observability import configure_logging, configure_telemetry
from app.db.base import engine
from app.db.session import get_db
from app.services.asset_pipeline import ASSET_ROOT
from app.services.migrations import migration_status, upgrade_to_head
from app.services.readiness import readiness_report


configure_logging()
log = structlog.get_logger(__name__) if structlog else logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_migrate:
        upgrade_to_head()
    elif settings.require_migration_head:
        status = migration_status()
        if not status["at_head"]:
            raise RuntimeError(f"Database migration is not at head: {status}")
    ASSET_ROOT.mkdir(parents=True, exist_ok=True)
    if structlog:
        log.info("application_started", version=settings.app_version, environment=settings.app_env)
    else:
        log.info("application_started version=%s environment=%s", settings.app_version, settings.app_env)
    yield
    if structlog:
        log.info("application_stopped", version=settings.app_version)
    else:
        log.info("application_stopped version=%s", settings.app_version)


app = FastAPI(
    title="OneAI Construction Twin",
    version=settings.app_version,
    description=(
        "Enterprise Pilot Edition: AI-native digital twin for construction and infrastructure. "
        "Evidence-first project intelligence, 4D BIM, distributed asset processing and human-governed agents."
    ),
    lifespan=lifespan,
)

app.add_middleware(EnterpriseMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Tenant-ID", "X-Organization-ID", "X-User-ID", "X-Role", "X-User-Email", "X-API-Key"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

app.include_router(projects_router)
app.include_router(demo_router)
app.include_router(read_router)
app.include_router(bim_router)
app.include_router(v03_router)
app.include_router(v04_router)
app.include_router(v05_router)
app.include_router(v06_router)
app.include_router(enterprise_router)

ASSET_ROOT.mkdir(parents=True, exist_ok=True)
# Generated assets are NEVER served through an unauthenticated static mount: every
# byte is delivered by GET /api/v1/generated-assets/{path} which enforces
# `twin:read` and rejects any key outside the caller's tenant prefix.
app.mount("/metrics", make_asgi_app())
configure_telemetry(app, engine)


@app.get("/health", tags=["health"])
def health():
    return {
        "status": "healthy",
        "service": "construction-twin-api",
        "version": settings.app_version,
        "edition": "Enterprise Pilot Edition",
    }


@app.get("/health/live", tags=["health"])
def liveness():
    return {"status": "alive", "version": settings.app_version}


@app.get("/health/ready", tags=["health"])
@app.get("/ready", tags=["health"], include_in_schema=False)
def readiness(response: Response, db: Session = Depends(get_db)):
    ok, report = readiness_report(db)
    if not ok:
        response.status_code = 503
    return report


@app.get("/version", tags=["health"])
def version():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "auth_mode": settings.auth_mode,
        "asset_pipeline": "distributed-content-addressed-3dtiles",
        "pilot": settings.pilot_name,
    }


@app.get("/")
def root():
    return {
        "name": "OneAI Construction Twin",
        "edition": f"v{settings.app_version} Enterprise Pilot Edition",
        "tagline": "AI-Native Digital Twin for Construction & Infrastructure",
        "pilot": settings.pilot_name,
        "docs": "/docs",
        "health": "/health",
        "readiness": "/health/ready",
    }
