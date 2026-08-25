"""Cross-project comparison.

The dashboard previously had no way to look at more than one project at a time, and a
browser-side comparison would have meant one request per project per metric. This
aggregates server-side, inside the caller's tenant scope, in a fixed number of queries.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import RequestContext
from app.core.time import utcnow
from app.domain.models import Activity, AgentAction, AssetBuildJob, Evidence, Project, Risk, TwinEntity
from app.services.schedule_analytics import collect_schedule_sample


def _counts(db: Session, ctx: RequestContext, model) -> dict[str, int]:
    """One grouped query per model rather than one query per project."""
    rows = db.execute(
        select(model.project_id, func.count())
        .where(model.tenant_id == ctx.tenant_id, model.organization_id == ctx.organization_id)
        .group_by(model.project_id)
    ).all()
    return {project_id: int(total) for project_id, total in rows}


def portfolio_summary(db: Session, ctx: RequestContext) -> dict[str, Any]:
    projects = list(
        db.scalars(
            select(Project)
            .where(Project.tenant_id == ctx.tenant_id, Project.organization_id == ctx.organization_id)
            .order_by(Project.created_at.desc())
        ).all()
    )

    entities = _counts(db, ctx, TwinEntity)
    activities = _counts(db, ctx, Activity)
    evidence = _counts(db, ctx, Evidence)
    risks = _counts(db, ctx, Risk)
    actions = _counts(db, ctx, AgentAction)
    jobs = _counts(db, ctx, AssetBuildJob)

    rows: list[dict[str, Any]] = []
    for project in projects:
        sample = collect_schedule_sample(db, ctx.tenant_id, ctx.organization_id, project.id)
        late = sample.late_activities
        critical_late = [item for item in late if item.critical]
        variance = round(project.actual_progress - project.planned_progress, 2)
        rows.append(
            {
                "id": project.id,
                "name": project.name,
                "code": project.code,
                "status": project.status,
                "planned_progress": project.planned_progress,
                "actual_progress": project.actual_progress,
                "variance": variance,
                "forecast_delay_days": project.forecast_delay_days,
                "counts": {
                    "twin_entities": entities.get(project.id, 0),
                    "activities": activities.get(project.id, 0),
                    "evidence": evidence.get(project.id, 0),
                    "risks": risks.get(project.id, 0),
                    "agent_actions": actions.get(project.id, 0),
                    "asset_jobs": jobs.get(project.id, 0),
                },
                "schedule": {
                    "measured": sample.sample_size,
                    "late": len(late),
                    "critical_late": len(critical_late),
                    "mean_slip_days": round(sample.mean_slip, 2),
                    "worst_slip_days": round(max((item.slip_days for item in late), default=0.0), 2),
                    "data_quality": sample.data_quality,
                },
                "created_at": project.created_at,
            }
        )

    behind = [row for row in rows if row["variance"] < 0]
    return {
        "generated_at": utcnow(),
        "project_count": len(rows),
        "totals": {
            "behind_baseline": len(behind),
            "twin_entities": sum(row["counts"]["twin_entities"] for row in rows),
            "activities": sum(row["counts"]["activities"] for row in rows),
            "evidence": sum(row["counts"]["evidence"] for row in rows),
            "late_activities": sum(row["schedule"]["late"] for row in rows),
        },
        "worst_variance": min((row["variance"] for row in rows), default=0.0),
        "projects": rows,
        "note": "Schedule metrics are measured from imported activities; projects without a schedule report zero rather than an estimate.",
    }
