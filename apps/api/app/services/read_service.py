from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.security import RequestContext
from app.domain.models import Project, TwinEntity, Activity, Evidence, Risk, GraphRelation, AgentAction


def _project_scope(model, ctx: RequestContext, project_id: str):
    return select(model).where(model.tenant_id == ctx.tenant_id, model.organization_id == ctx.organization_id, model.project_id == project_id)


def get_project(db: Session, ctx: RequestContext, project_id: str):
    return db.scalar(select(Project).where(Project.id == project_id, Project.tenant_id == ctx.tenant_id, Project.organization_id == ctx.organization_id))


def get_entity(db: Session, ctx: RequestContext, project_id: str, entity_id: str):
    return db.scalar(select(TwinEntity).where(TwinEntity.id == entity_id, TwinEntity.project_id == project_id, TwinEntity.tenant_id == ctx.tenant_id, TwinEntity.organization_id == ctx.organization_id))


def list_activities(db: Session, ctx: RequestContext, project_id: str):
    return db.scalars(_project_scope(Activity, ctx, project_id)).all()


def list_evidence(db: Session, ctx: RequestContext, project_id: str):
    return db.scalars(_project_scope(Evidence, ctx, project_id).order_by(Evidence.created_at.desc())).all()


def list_risks(db: Session, ctx: RequestContext, project_id: str):
    return db.scalars(_project_scope(Risk, ctx, project_id).order_by(Risk.created_at.desc())).all()


def list_graph(db: Session, ctx: RequestContext, project_id: str):
    return db.scalars(_project_scope(GraphRelation, ctx, project_id)).all()


def list_actions(db: Session, ctx: RequestContext, project_id: str):
    return db.scalars(_project_scope(AgentAction, ctx, project_id).order_by(AgentAction.created_at.desc())).all()
