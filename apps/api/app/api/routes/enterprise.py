from __future__ import annotations

from app.core.time import utcnow

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    ROLE_PERMISSIONS,
    RequestContext,
    get_context,
    issue_local_token,
    permissions_for_role,
    require,
)
from app.db.session import get_db
from app.domain.models import (
    Activity,
    AgentAction,
    AssetBuildJob,
    AuditLog,
    Evidence,
    Project,
    Risk,
    TwinEntity,
    WorkerHeartbeat,
)
from app.services.audit import verify_audit_chain
from app.services.readiness import readiness_report
from app.services.worker_heartbeat import active_workers


router = APIRouter(prefix="/api/v1", tags=["enterprise-pilot"])


class DevTokenRequest(BaseModel):
    user_id: str = "pilot-admin"
    tenant_id: str = "demo-tenant"
    organization_id: str = "demo-org"
    role: str = "platform_admin"
    email: str | None = None
    expires_minutes: int = Field(default=60, ge=5, le=1440)


@router.post("/auth/dev-token")
def dev_token(payload: DevTokenRequest):
    if settings.is_production or not settings.allow_dev_header_auth:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.role not in ROLE_PERMISSIONS:
        raise HTTPException(status_code=400, detail=f"Unknown role: {payload.role}")
    token = issue_local_token(
        user_id=payload.user_id,
        tenant_id=payload.tenant_id,
        organization_id=payload.organization_id,
        role=payload.role,
        email=payload.email,
        expires_minutes=payload.expires_minutes,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": payload.expires_minutes * 60,
        "role": payload.role,
    }


@router.get("/auth/me")
def auth_me(ctx: RequestContext = Depends(get_context)):
    return {
        "user_id": ctx.user_id,
        "email": ctx.email,
        "tenant_id": ctx.tenant_id,
        "organization_id": ctx.organization_id,
        "role": ctx.role,
        "permissions": sorted(permissions_for_role(ctx.role)),
        "auth_source": ctx.auth_source,
    }


@router.get("/admin/readiness")
def admin_readiness(db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "admin:read")
    ok, report = readiness_report(db)
    return {**report, "ok": ok}


@router.get("/admin/workers")
def workers(db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "admin:read")
    rows = active_workers(db)
    return [
        {
            "worker_id": row.worker_id,
            "worker_type": row.worker_type,
            "status": row.status,
            "version": row.version,
            "meta": row.meta,
            "started_at": row.started_at,
            "last_seen_at": row.last_seen_at,
        }
        for row in rows
    ]


@router.get("/projects/{project_id}/audit")
def project_audit(
    project_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "audit:read")
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == ctx.tenant_id,
            Project.organization_id == ctx.organization_id,
        )
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = db.scalars(
        select(AuditLog)
        .where(
            AuditLog.project_id == project_id,
            AuditLog.tenant_id == ctx.tenant_id,
            AuditLog.organization_id == ctx.organization_id,
        )
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "sequence": row.sequence,
            "prev_hash": row.prev_hash,
            "entry_hash": row.entry_hash,
            "actor_id": row.actor_id,
            "actor_type": row.actor_type,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "before": row.before,
            "after": row.after,
            "meta": row.meta,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/admin/audit/verify")
def audit_verify(
    limit: int | None = Query(default=None, ge=1, le=100_000),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """Recompute the tenant's audit hash chain and report the first break, if any."""
    require(ctx, "audit:read")
    return verify_audit_chain(db, ctx.tenant_id, limit)


@router.get("/projects/{project_id}/pilot-status")
def pilot_status(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "project:read")
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == ctx.tenant_id,
            Project.organization_id == ctx.organization_id,
        )
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    def count(model, *criteria):
        return int(db.scalar(select(func.count()).select_from(model).where(*criteria)) or 0)

    scope = (TwinEntity.project_id == project_id, TwinEntity.tenant_id == ctx.tenant_id, TwinEntity.organization_id == ctx.organization_id)
    entity_count = count(TwinEntity, *scope)
    activity_count = count(Activity, Activity.project_id == project_id, Activity.tenant_id == ctx.tenant_id, Activity.organization_id == ctx.organization_id)
    evidence_count = count(Evidence, Evidence.project_id == project_id, Evidence.tenant_id == ctx.tenant_id, Evidence.organization_id == ctx.organization_id)
    risk_count = count(Risk, Risk.project_id == project_id, Risk.tenant_id == ctx.tenant_id, Risk.organization_id == ctx.organization_id)
    action_count = count(AgentAction, AgentAction.project_id == project_id, AgentAction.tenant_id == ctx.tenant_id, AgentAction.organization_id == ctx.organization_id)
    asset_jobs = count(AssetBuildJob, AssetBuildJob.project_id == project_id, AssetBuildJob.tenant_id == ctx.tenant_id, AssetBuildJob.organization_id == ctx.organization_id)
    completed_jobs = count(
        AssetBuildJob,
        AssetBuildJob.project_id == project_id,
        AssetBuildJob.tenant_id == ctx.tenant_id,
        AssetBuildJob.organization_id == ctx.organization_id,
        AssetBuildJob.status == "completed",
    )
    readiness = {
        "project_created": True,
        "twin_entities": entity_count > 0,
        "schedule_activities": activity_count > 0,
        "evidence": evidence_count > 0,
        "risk_engine": risk_count > 0,
        "agent_actions": action_count > 0,
        "streaming_assets": completed_jobs > 0,
    }
    score = round(100 * sum(1 for value in readiness.values() if value) / len(readiness), 1)
    return {
        "pilot": settings.pilot_name,
        "project": {
            "id": project.id,
            "name": project.name,
            "code": project.code,
            "planned_progress": project.planned_progress,
            "actual_progress": project.actual_progress,
            "forecast_delay_days": project.forecast_delay_days,
        },
        "counts": {
            "twin_entities": entity_count,
            "activities": activity_count,
            "evidence": evidence_count,
            "risks": risk_count,
            "agent_actions": action_count,
            "asset_jobs": asset_jobs,
            "completed_asset_jobs": completed_jobs,
        },
        "readiness": readiness,
        "pilot_readiness_score": score,
        "evidence_policy": "No AI conclusion without evidence",
        "generated_at": utcnow(),
    }


@router.get("/pilot/checklist")
def pilot_checklist(ctx: RequestContext = Depends(get_context)):
    require(ctx, "project:read")
    return {
        "edition": f"OneAI Construction Twin v{settings.app_version} Enterprise Pilot Edition",
        "scenario": settings.pilot_name,
        "required_inputs": [
            "IFC model",
            "baseline schedule (P6/MS Project/CSV)",
            "daily reports",
            "progress photos",
            "RFI/NCR",
            "inspection records",
        ],
        "required_outputs": [
            "actual versus planned",
            "delay cause with evidence",
            "downstream impact",
            "P10/P50/P90 forecast",
            "mitigation scenarios",
            "human-approved actions",
            "immutable audit trail",
        ],
        "pilot_slo": {
            "api_p95_ms": 500,
            "ask_twin_first_response_seconds": 5,
            "project_home_seconds": 3,
            "medium_bim_first_view_seconds": 10,
            "availability_target": "99.5%",
            "critical_audit_coverage": "100%",
            "ai_evidence_coverage": "100%",
        },
    }
