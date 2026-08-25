"""Data exports.

Two rules here. First, an export is a security-relevant event - it takes project data
out of the system - so every export writes an audit entry naming what left and how many
rows. Second, exports carry the same provenance the UI shows: a forecast column without
its calibration state would be misleading the moment it lands in a spreadsheet.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import RequestContext
from app.core.time import utcnow
from app.core.version import APP_VERSION
from app.domain.models import Activity, AuditLog, Comment, Evidence, Project, Risk, TwinEntity
from app.services.audit import audit

EXPORTS = {"activities", "entities", "evidence", "risks", "audit", "comments"}


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


def _write_csv(header: list[str], rows: Iterable[list[Any]]) -> tuple[str, int]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    count = 0
    for row in rows:
        writer.writerow(row)
        count += 1
    return buffer.getvalue(), count


def _scoped(db: Session, ctx: RequestContext, model, project_id: str):
    return db.scalars(
        select(model).where(
            model.project_id == project_id,
            model.tenant_id == ctx.tenant_id,
            model.organization_id == ctx.organization_id,
        )
    ).all()


def export_csv(db: Session, ctx: RequestContext, project_id: str, dataset: str) -> tuple[str, str]:
    """Return (csv_text, filename). Raises ValueError for an unknown dataset."""
    if dataset not in EXPORTS:
        raise ValueError(f"Unknown export: {dataset}. Available: {', '.join(sorted(EXPORTS))}")
    project = _project(db, ctx, project_id)

    if dataset == "activities":
        rows = _scoped(db, ctx, Activity, project_id)
        content, count = _write_csv(
            ["external_id", "name", "planned_start", "planned_finish", "actual_start", "actual_finish",
             "percent_complete", "total_float_days", "critical"],
            ([r.external_id, r.name, r.planned_start, r.planned_finish, r.actual_start, r.actual_finish,
              r.percent_complete, r.total_float_days, r.critical] for r in rows),
        )
    elif dataset == "entities":
        rows = _scoped(db, ctx, TwinEntity, project_id)
        content, count = _write_csv(
            ["id", "name", "entity_type", "ifc_guid", "ifc_type", "zone", "status", "progress", "delay_days"],
            ([r.id, r.name, r.entity_type, (r.external_ids or {}).get("ifcGuid"), (r.external_ids or {}).get("ifcType"),
              (r.spatial or {}).get("zone"), (r.lifecycle or {}).get("actualStatus"),
              (r.lifecycle or {}).get("progress"), (r.lifecycle or {}).get("delayDays")] for r in rows),
        )
    elif dataset == "evidence":
        rows = _scoped(db, ctx, Evidence, project_id)
        content, count = _write_csv(
            ["id", "source_type", "source_id", "confidence", "created_at", "content"],
            ([r.id, r.source_type, r.source_id, r.confidence, r.created_at, r.content] for r in rows),
        )
    elif dataset == "risks":
        rows = _scoped(db, ctx, Risk, project_id)
        content, count = _write_csv(
            # `calibrated` is exported explicitly: a probability column in a spreadsheet
            # with no indication that the model is uncalibrated invites false confidence.
            ["id", "category", "title", "probability", "impact", "exposure", "status", "calibrated", "created_at", "causes"],
            ([r.id, r.category, r.title, r.probability, r.impact, r.exposure, r.status, "false", r.created_at,
              " | ".join(r.causes or [])] for r in rows),
        )
    elif dataset == "comments":
        rows = db.scalars(
            select(Comment).where(
                Comment.project_id == project_id,
                Comment.tenant_id == ctx.tenant_id,
                Comment.organization_id == ctx.organization_id,
            ).order_by(Comment.created_at)
        ).all()
        content, count = _write_csv(
            ["id", "target_type", "target_id", "parent_id", "author_id", "author_role", "resolved", "created_at", "body"],
            ([r.id, r.target_type, r.target_id, r.parent_id, r.author_id, r.author_role, r.resolved, r.created_at, r.body]
             for r in rows),
        )
    else:  # audit
        rows = db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id,
                AuditLog.tenant_id == ctx.tenant_id,
                AuditLog.organization_id == ctx.organization_id,
            ).order_by(AuditLog.sequence)
        ).all()
        content, count = _write_csv(
            ["sequence", "created_at", "action", "actor_id", "actor_type", "resource_type", "resource_id",
             "prev_hash", "entry_hash"],
            ([r.sequence, r.created_at, r.action, r.actor_id, r.actor_type, r.resource_type, r.resource_id,
              r.prev_hash, r.entry_hash] for r in rows),
        )

    audit(db, ctx, "data.export", "project", project_id, project_id,
          after={"dataset": dataset, "rows": count, "format": "csv", "app_version": APP_VERSION})
    db.commit()
    stamp = utcnow().strftime("%Y%m%d-%H%M")
    return content, f"{project.code or project.id}-{dataset}-{stamp}.csv"


def project_report(db: Session, ctx: RequestContext, project_id: str) -> dict[str, Any]:
    """Everything a printable project report needs, in one response."""
    from app.services.collaboration import list_comments
    from app.services.schedule_analytics import collect_schedule_sample

    project = _project(db, ctx, project_id)
    sample = collect_schedule_sample(db, ctx.tenant_id, ctx.organization_id, project_id)
    risks = _scoped(db, ctx, Risk, project_id)
    entities = _scoped(db, ctx, TwinEntity, project_id)
    evidence = _scoped(db, ctx, Evidence, project_id)
    latest_risk = max(risks, key=lambda row: row.created_at, default=None)

    audit(db, ctx, "report.generate", "project", project_id, project_id, after={"format": "report"})
    db.commit()

    return {
        "generated_at": utcnow(),
        "generated_by": {"user_id": ctx.user_id, "role": ctx.role, "auth_source": ctx.auth_source},
        "app_version": APP_VERSION,
        "project": {
            "id": project.id,
            "name": project.name,
            "code": project.code,
            "description": project.description,
            "planned_progress": project.planned_progress,
            "actual_progress": project.actual_progress,
            "variance": round(project.actual_progress - project.planned_progress, 2),
            "forecast_delay_days": project.forecast_delay_days,
        },
        "counts": {
            "twin_entities": len(entities),
            "activities": sample.total_activities,
            "evidence": len(evidence),
            "risks": len(risks),
        },
        "schedule": {
            "measured": sample.sample_size,
            "data_quality": sample.data_quality,
            "mean_slip_days": round(sample.mean_slip, 2),
            "critical_mean_slip_days": round(sample.critical_mean_slip, 2),
            "late": [
                {
                    "external_id": item.external_id,
                    "name": item.name,
                    "slip_days": item.slip_days,
                    "critical": item.critical,
                    "float_days": item.total_float_days,
                    "state": item.state,
                }
                for item in sample.late_activities[:25]
            ],
        },
        "latest_risk": None
        if not latest_risk
        else {
            "title": latest_risk.title,
            "probability": latest_risk.probability,
            "impact": latest_risk.impact,
            "exposure": latest_risk.exposure,
            "causes": latest_risk.causes,
            "mitigations": latest_risk.mitigations,
            "created_at": latest_risk.created_at,
        },
        "open_comments": [row for row in list_comments(db, ctx, project_id, include_resolved=False)][:25],
        "disclosure": (
            "Risk and forecast figures in this report come from uncalibrated heuristics over the "
            "project's own activity variance. They are indicative and must not be used as the sole "
            "basis for a contractual decision."
        ),
    }
