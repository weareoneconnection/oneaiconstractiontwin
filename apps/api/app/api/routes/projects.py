from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.core.security import get_context, RequestContext, require
from app.domain.schemas import (
    ProjectCreate, ProjectOut, TwinEntityCreate, TwinEntityOut, AskRequest, AskResponse,
    SimulationRequest, SimulationResponse, AgentRunRequest, AgentActionOut,
    ActionApproveRequest, ActionDispatchRequest, ExecutionReportIn, ExecutionReportOut,
    EvidenceIngestRequest, EvidenceIngestOut,
)
from app.services.action_execution import (
    ActionNotDispatchable, ActionNotFound, dispatch_action, ingest_evidence,
    record_execution, stale_dispatched_actions,
)
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
def action_approve(
    action_id: str,
    req: ActionApproveRequest | None = None,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """Approve an action and, when a distribution list is given, act on it.

    Dispatch failures do not fail the approval. The human's decision is recorded
    either way; what is recorded alongside it is whether the action reached
    anyone, which is a separate fact and is never assumed.
    """
    require(ctx, "action:approve")
    try:
        action = approve_action(db, ctx, action_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    request = req or ActionApproveRequest()
    if not request.dispatch or not request.recipients:
        return action

    try:
        return dispatch_action(
            db, ctx, action_id,
            [item.model_dump() for item in request.recipients],
            request.attachments,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    except ActionNotDispatchable as e:
        raise HTTPException(409, str(e))
    except ActionNotFound as e:
        raise HTTPException(404, str(e))


@router.post("/actions/{action_id}/dispatch", response_model=AgentActionOut)
def action_dispatch(
    action_id: str,
    req: ActionDispatchRequest,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """Send an already-approved action out, or retry one whose dispatch failed."""
    require(ctx, "action:approve")
    try:
        return dispatch_action(
            db, ctx, action_id,
            [item.model_dump() for item in req.recipients],
            req.attachments,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    except ActionNotDispatchable as e:
        raise HTTPException(409, str(e))
    except ActionNotFound as e:
        raise HTTPException(404, str(e))


@router.post("/actions/{action_id}/execution", response_model=ExecutionReportOut)
def action_execution_report(
    action_id: str,
    req: ExecutionReportIn,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """The executor's return path.

    Guarded by `action:execute`, which only the executor's own credential holds.
    That role can neither approve nor propose, so a stolen executor key cannot
    manufacture the approval it would need for anything to be dispatched to it.
    """
    require(ctx, "action:execute")
    try:
        action, created = record_execution(
            db, ctx, action_id,
            outcome=req.outcome,
            oneclaw_task_id=req.oneclaw_task_id,
            summary=req.summary,
            receipts=req.receipts,
            error=req.error,
            evidence=[item.model_dump() for item in req.evidence],
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    except ActionNotDispatchable as e:
        raise HTTPException(409, str(e))
    except ActionNotFound as e:
        raise HTTPException(404, str(e))

    return ExecutionReportOut(
        id=action.id,
        status=action.status,
        outcome=req.outcome.strip().lower(),
        evidence_created=created,
        executor_task_id=action.executor_task_id,
    )


@router.post("/projects/{project_id}/evidence/ingest", response_model=EvidenceIngestOut)
def evidence_ingest(
    project_id: str,
    req: EvidenceIngestRequest,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """Evidence collected outside the twin and written back into it.

    Collection changes nothing on the project, so it needs no approval — but it
    does need a credential that cannot do anything else, which is why this sits
    behind `evidence:write` rather than the broader twin write permission.
    """
    require(ctx, "evidence:write")
    try:
        created = ingest_evidence(db, ctx, project_id, [item.model_dump() for item in req.records])
    except ActionNotFound as e:
        raise HTTPException(404, str(e))
    return EvidenceIngestOut(project_id=project_id, created=created, submitted=len(req.records))


@router.get("/actions/unconfirmed")
def actions_unconfirmed(db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    """Actions handed to an executor that never reported back."""
    require(ctx, "action:approve")
    return {"actions": stale_dispatched_actions(db, ctx)}
