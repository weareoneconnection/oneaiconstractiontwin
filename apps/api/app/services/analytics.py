"""Time-series analytics derived from the project's own records.

There is no progress-history table in this system, so a "progress over time" chart could
only be invented — and an invented trend line is worse than no chart. What *is* real is
the schedule: every activity carries planned and actual dates. From those, two curves
can be computed honestly:

* the **planned S-curve**, the cumulative share of work the baseline said would be
  complete by each date, and
* the **actual S-curve**, the cumulative share actually completed by each date.

Both are count-weighted (each activity counts once) rather than duration- or
cost-weighted, because this codebase does not hold activity cost or resource loading.
That choice is reported in the response, since a count-weighted S-curve reads
differently from the cost-loaded curve a planner is used to.
"""

from __future__ import annotations

from datetime import date as date_type, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import RequestContext
from app.core.time import utcnow
from app.domain.models import Activity, AuditLog, Project

MAX_POINTS = 400


def _as_date(value: datetime | None) -> date_type | None:
    return value.date() if isinstance(value, datetime) else None


def _sample_dates(start: date_type, end: date_type) -> list[date_type]:
    """At most MAX_POINTS evenly spaced days, always including both ends."""
    total_days = max(1, (end - start).days)
    step = max(1, total_days // MAX_POINTS + (1 if total_days % MAX_POINTS else 0))
    points = [start + timedelta(days=offset) for offset in range(0, total_days + 1, step)]
    if points[-1] != end:
        points.append(end)
    return points


def schedule_curve(db: Session, ctx: RequestContext, project_id: str) -> dict[str, Any]:
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == ctx.tenant_id,
            Project.organization_id == ctx.organization_id,
        )
    )
    if not project:
        raise ValueError("Project not found")

    activities = list(
        db.scalars(
            select(Activity).where(
                Activity.project_id == project_id,
                Activity.tenant_id == ctx.tenant_id,
                Activity.organization_id == ctx.organization_id,
            )
        ).all()
    )
    planned_finishes = [d for d in (_as_date(a.planned_finish) for a in activities) if d]
    if not planned_finishes:
        return {
            "available": False,
            "reason": "No activity in this project has a planned finish date, so no baseline curve exists.",
            "method": "count-weighted-s-curve",
            "series": [],
            "activity_count": len(activities),
        }

    actual_finishes = [d for d in (_as_date(a.actual_finish) for a in activities) if d]
    starts = [d for d in (_as_date(a.planned_start) for a in activities) if d]
    start = min(starts or planned_finishes)
    end = max(planned_finishes + actual_finishes)
    today = utcnow().date()
    total = len(activities)

    series: list[dict[str, Any]] = []
    for point in _sample_dates(start, end):
        planned_done = sum(1 for a in activities if (_as_date(a.planned_finish) or end) <= point)
        actual_done = sum(1 for a in activities if (_as_date(a.actual_finish) or None) and _as_date(a.actual_finish) <= point)
        # Partial credit for work in progress, but only up to today: crediting future
        # progress would draw an actual curve into dates that have not happened.
        in_progress = 0.0
        if point <= today:
            for activity in activities:
                finished = _as_date(activity.actual_finish)
                started = _as_date(activity.actual_start)
                if finished and finished <= point:
                    continue
                if started and started <= point:
                    in_progress += min(0.99, max(0.0, float(activity.percent_complete or 0) / 100.0))
        series.append(
            {
                "date": point.isoformat(),
                "planned": round(100.0 * planned_done / total, 2),
                "actual": None if point > today else round(min(100.0, 100.0 * (actual_done + in_progress) / total), 2),
            }
        )

    latest = next((row for row in reversed(series) if row["actual"] is not None), None)
    variance = round((latest["actual"] - latest["planned"]), 2) if latest else 0.0

    return {
        "available": True,
        "method": "count-weighted-s-curve",
        "weighting": "each activity counts once; activity cost and resource loading are not held by this system",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "today": today.isoformat(),
        "activity_count": total,
        "series": series,
        "current": None
        if not latest
        else {"date": latest["date"], "planned": latest["planned"], "actual": latest["actual"], "variance": variance},
        "note": "Actual is only drawn up to today. Points after today show the baseline alone.",
    }


def slippage_trend(db: Session, ctx: RequestContext, project_id: str) -> dict[str, Any]:
    """How much finish-date slippage had accumulated by each date it occurred."""
    activities = list(
        db.scalars(
            select(Activity).where(
                Activity.project_id == project_id,
                Activity.tenant_id == ctx.tenant_id,
                Activity.organization_id == ctx.organization_id,
                Activity.actual_finish.is_not(None),
                Activity.planned_finish.is_not(None),
            ).order_by(Activity.actual_finish)
        ).all()
    )
    points: list[dict[str, Any]] = []
    cumulative = 0.0
    for activity in activities:
        slip = round((activity.actual_finish - activity.planned_finish).total_seconds() / 86400.0, 2)
        if slip <= 0:
            continue
        cumulative += slip
        points.append(
            {
                "date": _as_date(activity.actual_finish).isoformat(),
                "activity": activity.external_id,
                "slip_days": slip,
                "cumulative_slip_days": round(cumulative, 2),
                "critical": bool(activity.critical),
            }
        )
    return {
        "available": bool(points),
        "points": points,
        "total_slip_days": round(cumulative, 2),
        "note": "Only completed activities that finished after their planned date appear here.",
    }


def activity_timeline(db: Session, ctx: RequestContext, project_id: str, days: int = 30) -> dict[str, Any]:
    """Audit events per day: what the team and the agents actually did, and when."""
    since = utcnow() - timedelta(days=max(1, min(days, 365)))
    rows = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.project_id == project_id,
                AuditLog.tenant_id == ctx.tenant_id,
                AuditLog.organization_id == ctx.organization_id,
                AuditLog.created_at >= since,
            ).order_by(AuditLog.created_at)
        ).all()
    )
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        key = row.created_at.date().isoformat()
        bucket = buckets.setdefault(key, {"date": key, "human": 0, "agent": 0, "total": 0})
        bucket["agent" if row.actor_type == "agent" else "human"] += 1
        bucket["total"] += 1
    return {"days": days, "buckets": sorted(buckets.values(), key=lambda item: item["date"]), "total_events": len(rows)}
