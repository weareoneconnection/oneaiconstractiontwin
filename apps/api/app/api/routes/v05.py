from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.security import RequestContext, get_context, require
from app.db.session import get_db
from app.services.asset_pipeline import (
    AssetAccessDenied,
    asset_manifest,
    build_streaming_assets,
    resolve_generated_asset,
    spatial_query,
)
from app.services.object_storage import guess_content_type

router = APIRouter(prefix="/api/v1", tags=["v0.5-streaming-3dtiles"])


@router.post("/projects/{project_id}/bim/models/{document_id}/assets/build")
def build_assets(
    project_id: str,
    document_id: str,
    longitude: float = Query(101.6869),
    latitude: float = Query(3.1390),
    height: float = Query(0.0),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:write")
    try:
        return build_streaming_assets(db, ctx, project_id, document_id, longitude, latitude, height)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/projects/{project_id}/bim/models/{document_id}/assets")
def get_assets(project_id: str, document_id: str, ctx: RequestContext = Depends(get_context)):
    require(ctx, "twin:read")
    try:
        return asset_manifest(ctx, project_id, document_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/projects/{project_id}/bim/models/{document_id}/spatial-stream")
def stream_query(
    project_id: str,
    document_id: str,
    minx: float,
    miny: float,
    minz: float,
    maxx: float,
    maxy: float,
    maxz: float,
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")
    try:
        return spatial_query(ctx, project_id, document_id, minx, miny, minz, maxx, maxy, maxz)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/generated-assets/{asset_path:path}")
def generated_asset(
    asset_path: str,
    ctx: RequestContext = Depends(get_context),
):
    """Authenticated, tenant-scoped delivery of generated tilesets and GLB payloads.

    This replaces the previous unauthenticated `/assets` static mount, which served
    every tenant's model geometry to anyone able to guess a path.
    """
    require(ctx, "twin:read")
    try:
        target = resolve_generated_asset(ctx, asset_path)
    except AssetAccessDenied as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not target.is_file():
        raise HTTPException(404, "Generated asset not found")
    return FileResponse(target, media_type=guess_content_type(target.name))
