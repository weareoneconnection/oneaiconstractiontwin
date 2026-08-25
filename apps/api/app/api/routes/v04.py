from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import RequestContext, get_context, require
from app.db.session import get_db
from app.services.geometry_service import geometry_for_model
from app.services.timeline_service import timeline_bounds, timeline_state

router = APIRouter(prefix="/api/v1", tags=["v0.4-geometry-4d"])


@router.get("/projects/{project_id}/bim/models/{document_id}/geometry")
def model_geometry(
    project_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")
    try:
        return geometry_for_model(db, ctx, project_id, document_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/projects/{project_id}/timeline")
def timeline(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "project:read")
    return timeline_bounds(db, ctx, project_id)


@router.get("/projects/{project_id}/timeline/state")
def state_at(
    project_id: str,
    at: str = Query(..., description="ISO date YYYY-MM-DD"),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "project:read")
    try:
        when = datetime.strptime(at, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "at must be YYYY-MM-DD")
    return timeline_state(db, ctx, project_id, when)
