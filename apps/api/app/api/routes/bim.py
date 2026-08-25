from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.config import settings
from app.core.security import RequestContext, get_context, require
from app.db.session import get_db
from app.services.read_service import get_project
from sqlalchemy.orm import Session
from app.core.uploads import save_upload

router = APIRouter(prefix="/api/v1", tags=["bim"])
UPLOAD_ROOT = settings.upload_path
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


@router.post("/projects/{project_id}/bim/upload")
async def upload_bim(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:write")
    if not get_project(db, ctx, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    result = await save_upload(
        file,
        UPLOAD_ROOT / ctx.tenant_id / project_id,
        allowed={".ifc", ".glb", ".gltf", ".json"},
        fallback_name="model.ifc",
    )
    return {
        "status": "uploaded",
        "project_id": project_id,
        "filename": result["filename"],
        "storage_path": str(result["path"]),
        "bytes": result["bytes"],
        "sha256": result["sha256"],
        "max_upload_mb": settings.max_upload_mb,
        "adapter_status": "ready_for_ifc_semantic_pipeline",
    }
