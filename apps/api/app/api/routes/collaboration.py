from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import RequestContext, get_context, require
from app.db.session import get_db
from app.services.collaboration import create_comment, list_comments, resolve_comment
from app.services.exports import export_csv, project_report
from app.services.analytics import activity_timeline, schedule_curve, slippage_trend
from app.services.portfolio import portfolio_summary

router = APIRouter(prefix="/api/v1", tags=["collaboration-and-reporting"])


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    target_type: str = "project"
    target_id: str = ""
    parent_id: str | None = None


class CommentResolve(BaseModel):
    resolved: bool = True


@router.get("/portfolio/summary")
def portfolio(db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    """Cross-project comparison, aggregated server-side within the caller's tenant."""
    require(ctx, "project:read")
    return portfolio_summary(db, ctx)


@router.get("/projects/{project_id}/comments")
def comments(
    project_id: str,
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    include_resolved: bool = Query(default=True),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "project:read")
    try:
        return list_comments(db, ctx, project_id, target_type, target_id, include_resolved)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post("/projects/{project_id}/comments")
def add_comment(
    project_id: str,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "comment:write")
    try:
        return create_comment(db, ctx, project_id, payload.body, payload.target_type, payload.target_id, payload.parent_id)
    except ValueError as exc:
        raise HTTPException(400 if "not found" not in str(exc).lower() else 404, str(exc))


@router.post("/projects/{project_id}/comments/{comment_id}/resolve")
def set_resolved(
    project_id: str,
    comment_id: str,
    payload: CommentResolve,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "comment:write")
    try:
        return resolve_comment(db, ctx, project_id, comment_id, payload.resolved)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/projects/{project_id}/report")
def report(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    """Structured content for the printable project report."""
    require(ctx, "project:read")
    try:
        return project_report(db, ctx, project_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/projects/{project_id}/exports/{dataset}.csv")
def export_dataset(
    project_id: str,
    dataset: str,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """CSV export. Audit trails additionally require `audit:read`."""
    require(ctx, "project:read")
    if dataset == "audit":
        require(ctx, "audit:read")
    try:
        content, filename = export_csv(db, ctx, project_id, dataset)
    except ValueError as exc:
        raise HTTPException(404 if "not found" in str(exc).lower() else 400, str(exc))
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{project_id}/analytics/s-curve")
def s_curve(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    """Planned vs actual cumulative completion, derived from activity dates."""
    require(ctx, "project:read")
    try:
        return schedule_curve(db, ctx, project_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/projects/{project_id}/analytics/slippage")
def slippage(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "project:read")
    return slippage_trend(db, ctx, project_id)


@router.get("/projects/{project_id}/analytics/activity")
def activity(
    project_id: str,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """Audited events per day, split between human and agent actors."""
    require(ctx, "audit:read")
    return activity_timeline(db, ctx, project_id, days)
