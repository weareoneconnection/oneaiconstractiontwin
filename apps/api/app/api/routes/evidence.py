from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import RequestContext, get_context, require
from app.db.session import get_db
from app.domain.models import Evidence
from app.services.evidence_ingest import (
    SOURCE_TYPES,
    IngestError,
    coverage,
    import_evidence_csv,
    parse_date,
    store_photo_evidence,
)
from app.services.exif import read_exif
from app.services.object_storage import guess_content_type, storage

router = APIRouter(prefix="/api/v1", tags=["evidence"])

MAX_PHOTO_BYTES = 25 * 1024 * 1024
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


@router.get("/evidence/source-types")
def source_types():
    """The record types this deployment can ingest, for the uploader to choose from."""
    return {
        "source_types": sorted(SOURCE_TYPES),
        "csv_columns": {
            "required": ["content (or description / narrative / text)"],
            "recognised": [
                "source_id / id / reference", "date", "author / reported_by",
                "activity_id", "entity_guid / ifc_guid", "zone / location",
                "status / result", "title / subject", "confidence",
            ],
            "note": "Column names are matched case-insensitively against known aliases; unknown columns are ignored.",
        },
    }


@router.post("/projects/{project_id}/evidence/import-csv")
async def import_csv(
    project_id: str,
    source_type: str = Query(..., description="daily_report, rfi, ncr, inspection, delivery_record or note"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """Import site records as retrievable evidence. Re-importing a file is safe."""
    require(ctx, "twin:write")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "The uploaded file is empty.")
    try:
        return import_evidence_csv(db, ctx, project_id, source_type, raw)
    except IngestError as exc:
        raise HTTPException(404 if "not found" in str(exc).lower() else 400, str(exc))


@router.post("/projects/{project_id}/evidence/photos")
async def upload_photo(
    project_id: str,
    file: UploadFile = File(...),
    caption: str = Form(default=""),
    activity_id: str = Form(default=""),
    entity_guid: str = Form(default=""),
    taken_at: str = Form(default=""),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """Register a site photograph as evidence.

    Capture time is read from the image's own metadata when present, because a photo
    that reaches the office three days later is evidence about the day it was taken.
    """
    require(ctx, "twin:write")
    suffix = "." + (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if suffix not in PHOTO_TYPES:
        raise HTTPException(400, f"Unsupported image type '{suffix or 'unknown'}'. Accepted: {', '.join(sorted(PHOTO_TYPES))}")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "The uploaded image is empty.")
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(413, f"Image exceeds the {MAX_PHOTO_BYTES // (1024 * 1024)} MB limit.")

    metadata = read_exif(raw)
    captured = parse_date(taken_at) or metadata.get("taken_at")
    digest = hashlib.sha256(raw).hexdigest()
    # Content-addressed: the same photograph uploaded twice occupies one object.
    object_key = f"evidence/{ctx.tenant_id}/{project_id}/photos/{digest}{suffix}"
    storage.put_bytes(object_key, raw, guess_content_type(object_key))

    result = store_photo_evidence(
        db, ctx, project_id,
        object_key=object_key,
        filename=file.filename or f"{digest[:8]}{suffix}",
        caption=caption,
        taken_at=captured,
        activity_ref=activity_id,
        entity_ref=entity_guid,
        gps=metadata.get("gps"),
        sha256=digest,
    )
    return {**result, "bytes": len(raw), "exif_found": bool(metadata)}


@router.get("/projects/{project_id}/evidence/coverage")
def evidence_coverage(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """Which declared evidence sources this project actually has."""
    require(ctx, "twin:read")
    try:
        return coverage(db, ctx, project_id)
    except IngestError as exc:
        raise HTTPException(404, str(exc))


@router.get("/projects/{project_id}/evidence/{evidence_id}/image")
def evidence_image(
    project_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    """Deliver a photograph, scoped to the caller's tenant like every other asset."""
    require(ctx, "twin:read")
    row = db.scalar(
        select(Evidence).where(
            Evidence.id == evidence_id,
            Evidence.project_id == project_id,
            Evidence.tenant_id == ctx.tenant_id,
            Evidence.organization_id == ctx.organization_id,
        )
    )
    if not row:
        raise HTTPException(404, "Evidence not found")
    object_key = (row.fragment or {}).get("object_key")
    if not object_key:
        raise HTTPException(404, "This evidence record has no image attached")
    try:
        payload = storage.read_bytes(object_key)
    except Exception:
        raise HTTPException(404, "The stored image is no longer available")
    return Response(content=payload, media_type=guess_content_type(object_key))
