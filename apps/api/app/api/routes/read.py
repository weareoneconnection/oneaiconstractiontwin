from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import get_context, RequestContext, require
from app.domain.schemas import ProjectOut, TwinEntityOut
from app.services.read_service import get_project, get_entity, list_activities, list_evidence, list_risks, list_graph, list_actions

router = APIRouter(prefix="/api/v1", tags=["read-model"])


@router.get("/projects/{project_id}", response_model=ProjectOut)
def project_detail(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "project:read")
    row = get_project(db, ctx, project_id)
    if not row:
        raise HTTPException(404, "Project not found")
    return row


@router.get("/projects/{project_id}/entities/{entity_id}", response_model=TwinEntityOut)
def entity_detail(project_id: str, entity_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "twin:read")
    row = get_entity(db, ctx, project_id, entity_id)
    if not row:
        raise HTTPException(404, "Twin entity not found")
    return row


@router.get("/projects/{project_id}/activities")
def activities(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "project:read")
    rows = list_activities(db, ctx, project_id)
    return [{"id": r.id, "external_id": r.external_id, "name": r.name, "planned_start": r.planned_start, "planned_finish": r.planned_finish, "actual_start": r.actual_start, "actual_finish": r.actual_finish, "percent_complete": r.percent_complete, "total_float_days": r.total_float_days, "critical": r.critical, "meta": r.meta} for r in rows]


@router.get("/projects/{project_id}/evidence")
def evidence(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "twin:read")
    rows = list_evidence(db, ctx, project_id)
    return [{"id": r.id, "source_type": r.source_type, "source_id": r.source_id, "fragment": r.fragment, "confidence": r.confidence, "content": r.content, "created_at": r.created_at} for r in rows]


@router.get("/projects/{project_id}/risks")
def risks(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "project:read")
    rows = list_risks(db, ctx, project_id)
    return [{"id": r.id, "category": r.category, "title": r.title, "probability": r.probability, "impact": r.impact, "exposure": r.exposure, "causes": r.causes, "affected_entities": r.affected_entities, "evidence_ids": r.evidence_ids, "mitigations": r.mitigations, "status": r.status, "created_at": r.created_at} for r in rows]


@router.get("/projects/{project_id}/graph")
def graph(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "twin:read")
    rows = list_graph(db, ctx, project_id)
    return [{"id": r.id, "source_id": r.source_id, "relation": r.relation, "target_id": r.target_id, "meta": r.meta} for r in rows]


@router.get("/projects/{project_id}/actions")
def actions(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "project:read")
    rows = list_actions(db, ctx, project_id)
    return [{"id": r.id, "agent": r.agent, "action_type": r.action_type, "payload": r.payload, "status": r.status, "requested_by": r.requested_by, "approved_by": r.approved_by, "created_at": r.created_at, "approved_at": r.approved_at} for r in rows]
