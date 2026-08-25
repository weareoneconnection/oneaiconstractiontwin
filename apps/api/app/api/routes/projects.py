from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import get_context, RequestContext, require
from app.domain.schemas import ProjectCreate, ProjectOut, TwinEntityCreate, TwinEntityOut, AskRequest, AskResponse, SimulationRequest, SimulationResponse, AgentRunRequest, AgentActionOut
from app.services.project_service import list_projects, create_project, list_entities, create_entity
from app.services.read_service import get_project
from app.services.intelligence import ask_twin, evaluate_risks, forecast_project, simulate, run_agent, approve_action

router = APIRouter(prefix="/api/v1", tags=["construction-twin"])


@router.get("/projects", response_model=list[ProjectOut])
def projects(db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "project:read")
    return list_projects(db, ctx)


@router.post("/projects", response_model=ProjectOut)
def project_create(data: ProjectCreate, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "project:write")
    return create_project(db, ctx, data)


@router.get("/projects/{project_id}/entities", response_model=list[TwinEntityOut])
def entities(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "twin:read")
    return list_entities(db, ctx, project_id)


@router.post("/projects/{project_id}/entities", response_model=TwinEntityOut)
def entity_create(project_id: str, data: TwinEntityCreate, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "twin:write")
    return create_entity(db, ctx, project_id, data)


@router.post("/projects/{project_id}/ask", response_model=AskResponse)
async def ask(project_id: str, req: AskRequest, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "ai:run")
    try:
        return await ask_twin(db, ctx, project_id, req.question)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/projects/{project_id}/risks/evaluate")
def risks(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "ai:run")
    try:
        r, meta = evaluate_risks(db, ctx, project_id)
        return {
            "id": r.id,
            "category": r.category,
            "title": r.title,
            "probability": r.probability,
            "impact": r.impact,
            "exposure": r.exposure,
            "causes": r.causes,
            "mitigations": r.mitigations,
            "evidence_ids": r.evidence_ids,
            **meta,
        }
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/projects/{project_id}/forecast")
def forecast(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "ai:run")
    try:
        return forecast_project(db, ctx, project_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/projects/{project_id}/simulations", response_model=SimulationResponse)
def simulations(
    project_id: str,
    req: SimulationRequest,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "ai:run")
    project = get_project(db, ctx, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return simulate(req)


@router.post("/projects/{project_id}/agents/run", response_model=AgentActionOut)
def agents(project_id: str, req: AgentRunRequest, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "ai:run")
    try:
        return run_agent(db, ctx, project_id, req.agent, req.task)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post("/actions/{action_id}/approve", response_model=AgentActionOut)
def action_approve(action_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "action:approve")
    try:
        return approve_action(db, ctx, action_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
