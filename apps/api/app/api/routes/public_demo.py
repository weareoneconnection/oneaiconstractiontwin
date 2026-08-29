"""Unauthenticated, read-only demo surface for the marketing site.

Design rules, in order of importance:

1. **Off by default.** `public_demo_enabled` is False unless a deployment sets
   it. A customer installation cannot grow a public read surface by accident.
2. **The context is built here, never received.** Tenant, organization, role
   and user are constructed server-side from configuration. No header a caller
   sends can widen them, so the ordinary tenant scoping in the services below
   still does all the work it does for an authenticated request.
3. **One project.** Any id other than the configured demo project returns 404 —
   not 403, which would confirm that some other id exists.
4. **Read-only, and a narrow read at that.** No audit, no admin, no assets, no
   mutations. Adding an endpoint here is a deliberate act.
5. **The reasoner is reachable only through an allowlist.** An open text box on
   an unauthenticated endpoint is both a model bill and a prompt-injection
   surface aimed at a system that reads customer records.
"""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import RequestContext
from app.core.time import utcnow
from app.db.session import get_db
from app.services import intelligence
from app.services.analytics import schedule_curve
from app.services.read_service import get_project, list_activities, list_risks
from app.services.timeline_service import timeline_state

router = APIRouter(prefix="/api/v1/public/demo", tags=["public-demo"])


# --------------------------------------------------------------------------- guards


def _require_enabled() -> None:
    if not settings.public_demo_enabled:
        # 404 rather than 403: a disabled demo should look like no demo.
        raise HTTPException(status_code=404, detail="Not found")


def _demo_context() -> RequestContext:
    """The only identity this router ever runs as."""
    return RequestContext(
        tenant_id=settings.public_demo_tenant_id,
        organization_id=settings.public_demo_organization_id,
        user_id="public-demo",
        role="public_demo",
        email=None,
        auth_source="public-demo",
        claims={},
    )


def _demo_project_id() -> str:
    return settings.public_demo_project_id.strip()


class _Window:
    """Fixed-window counter, separate from the global limiter.

    The public surface needs a much tighter budget than an authenticated
    caller, and the reasoner needs a tighter one still.
    """

    def __init__(self) -> None:
        self._windows: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            count, expires = self._windows[key]
            if now >= expires:
                count, expires = 0, now + window_seconds
            count += 1
            self._windows[key] = (count, expires)
            if len(self._windows) > 50_000:
                for stale, (_, exp) in list(self._windows.items()):
                    if now >= exp:
                        del self._windows[stale]
            return count <= limit


_limiter = _Window()


def _client_fingerprint(request: Request) -> str:
    client_ip = request.client.host if request.client else "unknown"
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        client_ip = forwarded or client_ip
    return hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:16]


def _throttle(request: Request, bucket: str, limit: int) -> None:
    key = f"pd:{bucket}:{_client_fingerprint(request)}"
    if not _limiter.hit(key, limit, settings.public_demo_rate_limit_window_seconds):
        raise HTTPException(
            status_code=429,
            detail="Demo rate limit reached. Book a demo to see this on your own project.",
            headers={"Retry-After": str(settings.public_demo_rate_limit_window_seconds)},
        )


def demo_guard(request: Request) -> RequestContext:
    """Every endpoint in this router depends on this."""
    _require_enabled()
    _throttle(request, "read", settings.public_demo_rate_limit_requests)
    return _demo_context()


def _project_or_404(db: Session, ctx: RequestContext):
    project = get_project(db, ctx, _demo_project_id())
    if not project:
        raise HTTPException(status_code=404, detail="Demo project is not seeded")
    return project


# --------------------------------------------------------------------------- read


@router.get("/meta")
def meta(ctx: RequestContext = Depends(demo_guard)):
    """What this demo is, and what it deliberately is not.

    The marketing site renders this verbatim, so the disclosure travels with
    the data instead of being re-typed into a template that can drift.
    """
    return {
        "read_only": True,
        "project_id": _demo_project_id(),
        "allowed_questions": settings.public_demo_question_list,
        "disclosure": (
            "Read-only demonstration data from a seeded project. Risk and forecast "
            "figures are computed by the same code that runs on customer projects, "
            "but on demonstration data and without calibration against project history."
        ),
    }


@router.get("/project")
def project(db: Session = Depends(get_db), ctx: RequestContext = Depends(demo_guard)):
    row = _project_or_404(db, ctx)
    return {
        "id": row.id,
        "name": row.name,
        "planned_progress": row.planned_progress,
        "actual_progress": row.actual_progress,
    }


@router.get("/activities")
def activities(db: Session = Depends(get_db), ctx: RequestContext = Depends(demo_guard)):
    _project_or_404(db, ctx)
    rows = list_activities(db, ctx, _demo_project_id())
    return [
        {
            "id": row.id,
            "name": row.name,
            "percent_complete": row.percent_complete,
            "total_float_days": row.total_float_days,
            "critical": row.critical,
        }
        for row in rows
    ]


@router.get("/timeline")
def timeline(db: Session = Depends(get_db), ctx: RequestContext = Depends(demo_guard)):
    """Twin state at `now`. The demo has no date picker, by design.

    `utcnow()` is naive to match the DateTime columns; an aware datetime here
    raises on the first comparison against a stored date.
    """
    _project_or_404(db, ctx)
    return timeline_state(db, ctx, _demo_project_id(), utcnow())


@router.get("/s-curve")
def curve(db: Session = Depends(get_db), ctx: RequestContext = Depends(demo_guard)):
    _project_or_404(db, ctx)
    return schedule_curve(db, ctx, _demo_project_id())


@router.get("/risks")
def risks(db: Session = Depends(get_db), ctx: RequestContext = Depends(demo_guard)):
    _project_or_404(db, ctx)
    rows = list_risks(db, ctx, _demo_project_id())
    return [
        {
            "id": row.id,
            "category": row.category,
            "title": row.title,
            "probability": row.probability,
            "impact": row.impact,
            "exposure": row.exposure,
        }
        for row in rows
    ]


@router.get("/forecast")
def forecast(db: Session = Depends(get_db), ctx: RequestContext = Depends(demo_guard)):
    """P10/P50/P90 with the calibration state the product always reports."""
    _project_or_404(db, ctx)
    # A fixed seed keeps the marketing page from changing its numbers on every
    # reload, which would look like instability rather than a bootstrap.
    return intelligence.forecast_project(db, ctx, _demo_project_id(), seed=1)


# --------------------------------------------------------------------------- ask


class PublicAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=200)


@router.post("/ask")
async def ask(
    payload: PublicAskRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(demo_guard),
):
    """Answer one of the allowlisted questions against the demo project.

    The allowlist is compared exactly. Anything else is refused with the list
    of questions that are permitted, so the caller learns the boundary without
    learning anything about the project.
    """
    _throttle(request, "ask", settings.public_demo_ask_rate_limit_requests)

    allowed = settings.public_demo_question_list
    question = payload.question.strip()
    if question not in allowed:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "This demo answers a fixed set of questions.",
                "allowed_questions": allowed,
            },
        )

    _project_or_404(db, ctx)
    return await intelligence.ask_twin(db, ctx, _demo_project_id(), question)
