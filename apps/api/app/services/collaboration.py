"""Project comments.

Collaboration data is ordinary project data: tenant-scoped, permission-checked and
audited. Creating and resolving a comment both write audit entries, because "who
signed off on this recommendation" is exactly the kind of question a pilot review asks
afterwards.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import RequestContext
from app.core.time import utcnow
from app.domain.models import Comment, Project
from app.services.audit import audit

MAX_BODY = 4000
TARGET_TYPES = {"project", "twin_entity", "activity", "risk", "agent_action", "document"}


def _project(db: Session, ctx: RequestContext, project_id: str) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == ctx.tenant_id,
            Project.organization_id == ctx.organization_id,
        )
    )
    if not project:
        raise ValueError("Project not found")
    return project


def to_dict(row: Comment) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "parent_id": row.parent_id,
        "body": row.body,
        "author_id": row.author_id,
        "author_email": row.author_email,
        "author_role": row.author_role,
        "resolved": bool(row.resolved),
        "resolved_by": row.resolved_by,
        "resolved_at": row.resolved_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_comments(
    db: Session,
    ctx: RequestContext,
    project_id: str,
    target_type: str | None = None,
    target_id: str | None = None,
    include_resolved: bool = True,
    limit: int = 200,
) -> list[dict[str, Any]]:
    _project(db, ctx, project_id)
    query = select(Comment).where(
        Comment.project_id == project_id,
        Comment.tenant_id == ctx.tenant_id,
        Comment.organization_id == ctx.organization_id,
    )
    if target_type:
        query = query.where(Comment.target_type == target_type)
    if target_id:
        query = query.where(Comment.target_id == target_id)
    if not include_resolved:
        query = query.where(Comment.resolved.is_(False))
    rows = db.scalars(query.order_by(Comment.created_at).limit(max(1, min(limit, 1000)))).all()
    return [to_dict(row) for row in rows]


def create_comment(
    db: Session,
    ctx: RequestContext,
    project_id: str,
    body: str,
    target_type: str = "project",
    target_id: str = "",
    parent_id: str | None = None,
) -> dict[str, Any]:
    _project(db, ctx, project_id)
    text = (body or "").strip()
    if not text:
        raise ValueError("A comment cannot be empty")
    if len(text) > MAX_BODY:
        raise ValueError(f"A comment cannot exceed {MAX_BODY} characters")
    if target_type not in TARGET_TYPES:
        raise ValueError(f"Unsupported target type: {target_type}")
    if parent_id:
        parent = db.scalar(
            select(Comment).where(
                Comment.id == parent_id,
                Comment.project_id == project_id,
                Comment.tenant_id == ctx.tenant_id,
            )
        )
        if not parent:
            raise ValueError("Parent comment not found")
        # One level of threading only: deeper trees are hard to read and harder to
        # summarise in a report.
        if parent.parent_id:
            parent_id = parent.parent_id

    row = Comment(
        tenant_id=ctx.tenant_id,
        organization_id=ctx.organization_id,
        project_id=project_id,
        target_type=target_type,
        target_id=target_id or "",
        parent_id=parent_id,
        body=text,
        author_id=ctx.user_id,
        author_email=ctx.email,
        author_role=ctx.role,
    )
    db.add(row)
    db.flush()
    audit(
        db, ctx, "comment.create", "comment", row.id, project_id,
        after={"target_type": target_type, "target_id": target_id, "length": len(text), "parent_id": parent_id},
    )
    db.commit()
    db.refresh(row)
    return to_dict(row)


def resolve_comment(db: Session, ctx: RequestContext, project_id: str, comment_id: str, resolved: bool) -> dict[str, Any]:
    _project(db, ctx, project_id)
    row = db.scalar(
        select(Comment).where(
            Comment.id == comment_id,
            Comment.project_id == project_id,
            Comment.tenant_id == ctx.tenant_id,
            Comment.organization_id == ctx.organization_id,
        )
    )
    if not row:
        raise ValueError("Comment not found")
    before = {"resolved": bool(row.resolved)}
    row.resolved = resolved
    row.resolved_by = ctx.user_id if resolved else None
    row.resolved_at = utcnow() if resolved else None
    audit(db, ctx, "comment.resolve" if resolved else "comment.reopen", "comment", row.id, project_id,
          before=before, after={"resolved": resolved})
    db.commit()
    db.refresh(row)
    return to_dict(row)
