from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import RequestContext, get_context, require
from app.core.uploads import save_upload
from app.db.session import get_db
from app.domain.models import Document, MappingRule
from app.services.ifc_service import ingest_ifc
from app.services.mapping_service import auto_map, import_schedule_csv
from app.services.read_service import get_project

router = APIRouter(prefix="/api/v1", tags=["bim-schedule"])


@router.post("/projects/{project_id}/bim/import-ifc")
async def import_ifc(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:write")
    if not get_project(db, ctx, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    root = settings.upload_path
    result = await save_upload(file, root / ctx.tenant_id / project_id, allowed={".ifc"}, fallback_name="model.ifc")
    return ingest_ifc(db, ctx, project_id, str(result["path"]), str(result["filename"]))


@router.get("/projects/{project_id}/bim/models")
def bim_models(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "twin:read")
    rows = (
        db.query(Document)
        .filter(
            Document.project_id == project_id,
            Document.tenant_id == ctx.tenant_id,
            Document.organization_id == ctx.organization_id,
            Document.doc_type == "ifc_model",
        )
        .order_by(Document.created_at.desc())
        .all()
    )
    return [{"id": row.id, "title": row.title, "meta": row.meta, "created_at": row.created_at} for row in rows]


@router.post("/projects/{project_id}/schedules/import-csv")
async def schedule_csv(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "project:write")
    if not get_project(db, ctx, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV schedule files are accepted")
    raw = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    await file.close()
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Upload exceeds {settings.max_upload_mb} MB limit")
    return import_schedule_csv(db, ctx, project_id, raw)


@router.post("/projects/{project_id}/mappings/auto")
def mapping_auto(
    project_id: str,
    threshold: float = Query(0.18, ge=0, le=1),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:write")
    if not get_project(db, ctx, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return auto_map(db, ctx, project_id, threshold)


@router.get("/projects/{project_id}/mappings")
def mappings(project_id: str, db: Session = Depends(get_db), ctx: RequestContext = Depends(get_context)):
    require(ctx, "twin:read")
    rows = (
        db.query(MappingRule)
        .filter(
            MappingRule.project_id == project_id,
            MappingRule.tenant_id == ctx.tenant_id,
            MappingRule.organization_id == ctx.organization_id,
        )
        .order_by(MappingRule.confidence.desc())
        .all()
    )
    return [
        {"id": row.id, "source": row.source, "target": row.target, "strategy": row.strategy, "confidence": row.confidence}
        for row in rows
    ]
