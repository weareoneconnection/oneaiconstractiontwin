from datetime import timedelta
from app.core.time import utcnow
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import get_context, RequestContext
from app.domain.models import Organization, Project, TwinEntity, Activity, Evidence, GraphRelation
from app.core.config import settings

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


@router.post("/seed")
def seed(db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    if not settings.demo_endpoints_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    org = Organization(id=ctx.organization_id, tenant_id=ctx.tenant_id, name="OneAI Demo EPC")
    db.merge(org)

    # Seeding is idempotent per tenant/organization. Calling it repeatedly used to
    # pile up identical STN02 projects, and the dashboard then opened an arbitrary one.
    existing = db.query(Project).filter(
        Project.tenant_id == ctx.tenant_id,
        Project.organization_id == ctx.organization_id,
        Project.code == "STN02",
    ).order_by(Project.created_at.desc()).first()
    if existing:
        first_entity = db.query(TwinEntity).filter(TwinEntity.project_id == existing.id).first()
        activities = db.query(Activity).filter(Activity.project_id == existing.id).all()
        return {
            "project_id": existing.id,
            "already_seeded": True,
            "entity_id": first_entity.id if first_entity else None,
            "activity_id": activities[0].id if activities else None,
            "activity_ids": [row.id for row in activities],
            "evidence_ids": [row.id for row in db.query(Evidence).filter(Evidence.project_id == existing.id).all()],
        }

    project = Project(
        tenant_id=ctx.tenant_id, organization_id=ctx.organization_id,
        name="Station 02 Construction Twin", code="STN02",
        description="Demo railway station project", planned_progress=71.8, actual_progress=67.4, forecast_delay_days=11,
    )
    db.add(project); db.flush()
    beam = TwinEntity(
        tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project.id,
        entity_type="element", name="Beam B-023", external_ids={"ifcGuid": "3lXDemoB023"},
        spatial={"station": "Station 02", "zone": "Roof Zone B"},
        lifecycle={"plannedStatus": "installed", "actualStatus": "installed", "progress": 100, "plannedFinish": "2026-08-15", "actualFinish": "2026-08-19", "delayDays": 4},
        links={"activities": [], "documents": [], "evidence": []},
        intelligence={"healthScore": 82, "riskScore": 0.61, "aiSummary": "Installed four days late"},
    )
    db.add(beam); db.flush()
    # A single activity cannot support a forecast. The seed provides a small but
    # real schedule so the variance-driven risk and forecast engines have a sample
    # to work from, and so their "thin data" warning is visible when it applies.
    activity_specs = [
        # (external_id, name, planned_offset_start, planned_days, actual_offset_start, actual_days, percent, float_days, critical)
        ("A1023", "Roof steel installation Zone B", -12, 7, -10, 9, 100, 0, True),
        ("A1024", "Roof steel installation Zone C", -8, 6, -6, 8, 100, 0, True),
        ("A1025", "Connection plate welding Zone B", -6, 4, -4, 5, 100, 2, True),
        ("A1026", "Steel inspection Zone B", -4, 2, -2, 3, 100, 3, False),
        ("A1027", "Roof decking Zone B", -2, 5, -1, None, 60, 1, True),
        ("A1028", "Roof decking Zone C", 0, 5, None, None, 0, 4, False),
        ("A1029", "Fireproofing Zone B", 3, 6, None, None, 0, 6, False),
        ("A1030", "Handover inspection", 10, 3, None, None, 0, 8, True),
    ]
    activities = []
    for external_id, name, ps, pdays, a_s, adays, percent, float_days, critical in activity_specs:
        planned_start = utcnow() + timedelta(days=ps)
        actual_start = utcnow() + timedelta(days=a_s) if a_s is not None else None
        row = Activity(
            tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project.id,
            external_id=external_id, name=name,
            planned_start=planned_start,
            planned_finish=planned_start + timedelta(days=pdays),
            actual_start=actual_start,
            actual_finish=(actual_start + timedelta(days=adays)) if (actual_start and adays) else None,
            percent_complete=percent, total_float_days=float_days, critical=critical,
        )
        db.add(row)
        activities.append(row)
    db.flush()
    activity = activities[0]
    beam.links = {"activities": [activity.id], "documents": [], "evidence": []}
    e1 = Evidence(
        tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project.id,
        source_type="daily_report", source_id="DR-241", hash="demo-dr-241", confidence=0.98,
        content="15 Aug 2026: Crane C02 unavailable from 08:20 to 17:40; roof steel installation suspended."
    )
    e2 = Evidence(
        tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project.id,
        source_type="delivery_record", source_id="DLV-CP23", hash="demo-dlv-cp23", confidence=0.96,
        content="Connection Plate CP-23 delivered on 16 Aug 2026 at 14:20."
    )
    e3 = Evidence(
        tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project.id,
        source_type="ncr", source_id="NCR-118", hash="demo-ncr-118", confidence=0.94,
        content="17 Aug 2026: NCR-118 raised on Zone B weld quality; rework required on two connection plates before decking can start."
    )
    e4 = Evidence(
        tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project.id,
        source_type="inspection", source_id="INS-072", hash="demo-ins-072", confidence=0.97,
        content="19 Aug 2026: Steel inspection Zone B passed after rework; roof decking Zone B released for installation."
    )
    e5 = Evidence(
        tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project.id,
        source_type="daily_report", source_id="DR-246", hash="demo-dr-246", confidence=0.95,
        content="20 Aug 2026: Heavy rain from 11:00; roof decking Zone B crew stood down for the remainder of the shift."
    )
    db.add_all([e1,e2,e3,e4,e5]); db.flush()
    beam.links = {"activities": [activity.id], "documents": [], "evidence": [e1.id, e2.id]}
    db.add(GraphRelation(tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project.id, source_id=beam.id, relation="LINKED_TO", target_id=activity.id))
    db.add(GraphRelation(tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project.id, source_id=beam.id, relation="EVIDENCED_BY", target_id=e1.id))
    db.commit()
    return {
        "project_id": project.id,
        "already_seeded": False,
        "entity_id": beam.id,
        "activity_id": activity.id,
        "activity_ids": [row.id for row in activities],
        "evidence_ids": [e1.id, e2.id, e3.id, e4.id, e5.id],
    }
