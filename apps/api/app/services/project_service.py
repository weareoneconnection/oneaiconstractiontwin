from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.security import RequestContext
from app.domain.models import Project, TwinEntity
from app.domain.schemas import ProjectCreate, TwinEntityCreate
from app.services.events import emit
from app.services.audit import audit


def list_projects(db: Session, ctx: RequestContext):
    # Newest first: the dashboard opens the first entry, and an operator who has just
    # created or seeded a project expects to land on it.
    return db.scalars(
        select(Project)
        .where(Project.tenant_id == ctx.tenant_id, Project.organization_id == ctx.organization_id)
        .order_by(Project.created_at.desc())
    ).all()


def create_project(db: Session, ctx: RequestContext, data: ProjectCreate):
    row = Project(tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, **data.model_dump())
    db.add(row)
    db.flush()
    emit(db, "project.created", "project", row.id, {"project_id": row.id, "name": row.name})
    audit(db, ctx, "project.create", "project", row.id, row.id, after=data.model_dump())
    db.commit(); db.refresh(row)
    return row


def list_entities(db: Session, ctx: RequestContext, project_id: str):
    return db.scalars(select(TwinEntity).where(TwinEntity.tenant_id == ctx.tenant_id, TwinEntity.organization_id == ctx.organization_id, TwinEntity.project_id == project_id)).all()


def create_entity(db: Session, ctx: RequestContext, project_id: str, data: TwinEntityCreate):
    row = TwinEntity(tenant_id=ctx.tenant_id, organization_id=ctx.organization_id, project_id=project_id, **data.model_dump())
    db.add(row); db.flush()
    emit(db, "twin.entity.created", "twin_entity", row.id, {"project_id": project_id, "entity_id": row.id, "type": row.entity_type})
    audit(db, ctx, "twin.entity.create", "twin_entity", row.id, project_id, after=data.model_dump())
    db.commit(); db.refresh(row)
    return row
