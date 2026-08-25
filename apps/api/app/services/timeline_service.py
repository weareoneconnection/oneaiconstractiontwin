from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import RequestContext
from app.domain.models import Activity, TwinEntity


def _date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                return datetime.strptime(value[:26], fmt)
            except ValueError:
                pass
    return None


def _iso(d: datetime | None) -> str | None:
    return d.date().isoformat() if d else None


def _activity_state(activity: Activity, at: datetime) -> tuple[str, float]:
    ps, pf = activity.planned_start, activity.planned_finish
    a_s, a_f = activity.actual_start, activity.actual_finish
    if a_f and a_f <= at:
        return "completed", 1.0
    if a_s and a_s <= at and (not a_f or at < a_f):
        return "in_progress", min(0.99, max(0.05, activity.percent_complete / 100.0))
    if pf and at > pf and not a_f:
        return "delayed", min(0.99, max(0.0, activity.percent_complete / 100.0))
    if ps and ps <= at:
        if pf and pf > ps:
            frac = (at - ps).total_seconds() / max(1, (pf - ps).total_seconds())
            return "planned", max(0.05, min(0.95, frac))
        return "planned", 0.25
    return "future", 0.0


def _entity_state(entity: TwinEntity, activity_by_id: dict[str, Activity], at: datetime) -> dict[str, Any]:
    linked = [activity_by_id[x] for x in (entity.links or {}).get("activities", []) if x in activity_by_id]
    if linked:
        states = [_activity_state(a, at) for a in linked]
        rank = {"delayed": 5, "in_progress": 4, "planned": 3, "completed": 2, "future": 1}
        state, progress = max(states, key=lambda x: rank[x[0]])
        if all(s[0] == "completed" for s in states):
            state = "completed"
            progress = 1.0
        return {"state": state, "progress": round(progress, 4), "activity_ids": [a.id for a in linked]}

    lc = entity.lifecycle or {}
    ps = _date(lc.get("plannedStart"))
    pf = _date(lc.get("plannedFinish"))
    a_s = _date(lc.get("actualStart"))
    a_f = _date(lc.get("actualFinish"))
    pseudo = type("ActivityProxy", (), {
        "planned_start": ps, "planned_finish": pf, "actual_start": a_s, "actual_finish": a_f,
        "percent_complete": float(lc.get("progress") or 0),
    })()
    state, progress = _activity_state(pseudo, at)
    return {"state": state, "progress": round(progress, 4), "activity_ids": []}


def timeline_bounds(db: Session, ctx: RequestContext, project_id: str) -> dict[str, Any]:
    acts = db.query(Activity).filter(Activity.project_id == project_id, Activity.tenant_id == ctx.tenant_id, Activity.organization_id == ctx.organization_id).all()
    dates: list[datetime] = []
    for a in acts:
        dates += [d for d in (a.planned_start, a.planned_finish, a.actual_start, a.actual_finish) if d]
    if not dates:
        entities = db.query(TwinEntity).filter(TwinEntity.project_id == project_id, TwinEntity.tenant_id == ctx.tenant_id, TwinEntity.organization_id == ctx.organization_id).all()
        for e in entities:
            lc = e.lifecycle or {}
            dates += [d for d in (_date(lc.get("plannedStart")), _date(lc.get("plannedFinish")), _date(lc.get("actualStart")), _date(lc.get("actualFinish"))) if d]
    if not dates:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        dates = [now - timedelta(days=30), now + timedelta(days=60)]
    start, end = min(dates), max(dates)
    if start == end:
        end = start + timedelta(days=30)
    return {"start": _iso(start), "end": _iso(end), "days": max(1, (end.date() - start.date()).days)}


def timeline_state(db: Session, ctx: RequestContext, project_id: str, at: datetime) -> dict[str, Any]:
    entities = db.query(TwinEntity).filter(TwinEntity.project_id == project_id, TwinEntity.tenant_id == ctx.tenant_id, TwinEntity.organization_id == ctx.organization_id).all()
    acts = db.query(Activity).filter(Activity.project_id == project_id, Activity.tenant_id == ctx.tenant_id, Activity.organization_id == ctx.organization_id).all()
    by_id = {a.id: a for a in acts}
    items = []
    summary = {"future": 0, "planned": 0, "in_progress": 0, "delayed": 0, "completed": 0}
    for e in entities:
        st = _entity_state(e, by_id, at)
        summary[st["state"]] = summary.get(st["state"], 0) + 1
        items.append({"entity_id": e.id, "name": e.name, **st})
    return {"at": at.date().isoformat(), "summary": summary, "entities": items}
