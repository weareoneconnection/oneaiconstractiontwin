from __future__ import annotations

import asyncio
import json
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import RequestContext, get_context, require
from app.db.base import SessionLocal
from app.db.session import get_db
from app.domain.models import AssetCacheEntry
from app.domain.schemas import AssetBuildJobRequest
from app.services.asset_jobs import (
    TERMINAL_STATUSES,
    cancel_job,
    create_job,
    get_job,
    job_to_dict,
    list_events,
    list_jobs,
    list_partitions,
    partition_to_dict,
    resume_job,
)
from app.services.object_storage import guess_content_type, normalize_key, storage
from app.services.worker_signal import notify_workers

router = APIRouter(prefix="/api/v1", tags=["distributed-assets"])


@router.post("/projects/{project_id}/bim/models/{document_id}/asset-jobs")
def create_asset_job(
    project_id: str,
    document_id: str,
    payload: AssetBuildJobRequest,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:write")
    try:
        options = payload.model_dump(exclude={"force_rebuild"})
        job, deduplicated = create_job(db, ctx, project_id, document_id, options, payload.force_rebuild)
        return {**job_to_dict(job), "deduplicated": deduplicated}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/projects/{project_id}/bim/models/{document_id}/asset-jobs")
def model_asset_jobs(
    project_id: str,
    document_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")
    return [job_to_dict(row) for row in list_jobs(db, ctx, project_id, document_id, limit)]


@router.get("/projects/{project_id}/asset-jobs")
def project_asset_jobs(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")
    return [job_to_dict(row) for row in list_jobs(db, ctx, project_id, None, limit)]


@router.get("/asset-jobs/{job_id}")
def asset_job_detail(
    job_id: str,
    include_partitions: bool = Query(True),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")
    job = get_job(db, ctx, job_id)
    if not job:
        raise HTTPException(404, "Asset job not found")
    result = job_to_dict(job)
    if include_partitions:
        result["partitions"] = [partition_to_dict(row) for row in list_partitions(db, job.id)]
    return result


@router.get("/asset-jobs/{job_id}/events")
def asset_job_events(
    job_id: str,
    after_sequence: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")
    job = get_job(db, ctx, job_id)
    if not job:
        raise HTTPException(404, "Asset job not found")
    return [{
        "id": row.id,
        "sequence": row.sequence,
        "event_type": row.event_type,
        "message": row.message,
        "progress": row.progress,
        "payload": row.payload,
        "created_at": row.created_at,
    } for row in list_events(db, job.id, after_sequence)]


@router.get("/asset-jobs/{job_id}/events/stream")
async def asset_job_event_stream(
    job_id: str,
    request: Request,
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")

    async def events():
        last = 0
        while True:
            if await request.is_disconnected():
                break
            with SessionLocal() as db:
                job = get_job(db, ctx, job_id)
                if not job:
                    yield "event: error\ndata: {\"detail\":\"Asset job not found\"}\n\n"
                    break
                rows = list_events(db, job.id, last)
                for row in rows:
                    last = row.sequence
                    data = {
                        "sequence": row.sequence,
                        "event_type": row.event_type,
                        "message": row.message,
                        "progress": row.progress,
                        "payload": row.payload,
                        "created_at": row.created_at,
                    }
                    yield f"event: progress\ndata: {json.dumps(data, default=str)}\n\n"
                if job.status in TERMINAL_STATUSES:
                    yield f"event: terminal\ndata: {json.dumps(job_to_dict(job), default=str)}\n\n"
                    break
            await asyncio.sleep(0.75)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/asset-jobs/{job_id}/cancel")
def cancel_asset_job(
    job_id: str,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:write")
    try:
        return job_to_dict(cancel_job(db, ctx, job_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.post("/asset-jobs/{job_id}/resume")
def resume_asset_job(
    job_id: str,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:write")
    try:
        return job_to_dict(resume_job(db, ctx, job_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/asset-workers/wake")
def wake_asset_workers(ctx: RequestContext = Depends(get_context)):
    require(ctx, "twin:write")
    notify_workers(4)
    return {"status": "signalled"}


@router.get("/asset-jobs/{job_id}/manifest")
def asset_job_manifest(
    job_id: str,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")
    job = get_job(db, ctx, job_id)
    if not job:
        raise HTTPException(404, "Asset job not found")
    if not job.result_manifest_key:
        raise HTTPException(409, "Asset job has no completed manifest")
    try:
        return json.loads(storage.read_bytes(job.result_manifest_key))
    except FileNotFoundError:
        raise HTTPException(404, "Manifest object not found")


@router.get("/asset-cache/{cache_key}")
def asset_cache_detail(
    cache_key: str,
    db: Session = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")
    row = db.query(AssetCacheEntry).filter(
        AssetCacheEntry.cache_key == cache_key,
        AssetCacheEntry.tenant_id == ctx.tenant_id,
        AssetCacheEntry.organization_id == ctx.organization_id,
    ).first()
    if not row:
        raise HTTPException(404, "Cache entry not found")
    return {
        "cache_key": row.cache_key,
        "status": row.status,
        "source_sha256": row.source_sha256,
        "pipeline_version": row.pipeline_version,
        "manifest_key": row.manifest_key,
        "manifest_url": storage.api_url(row.manifest_key) if row.manifest_key else None,
        "size_bytes": row.size_bytes,
        "ref_count": row.ref_count,
        "meta": row.meta,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "last_accessed_at": row.last_accessed_at,
    }


@router.get("/asset-objects/{object_key:path}")
def asset_object(
    object_key: str,
    ctx: RequestContext = Depends(get_context),
):
    require(ctx, "twin:read")
    try:
        key = normalize_key(object_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not key.startswith(f"{settings.asset_object_prefix.strip('/')}/{ctx.tenant_id}/"):
        raise HTTPException(403, "Cross-tenant asset access denied")
    if not storage.exists(key):
        raise HTTPException(404, "Asset object not found")
    content_type = guess_content_type(key)
    local = storage.open_local(key)
    if local:
        return FileResponse(local, media_type=content_type, filename=None)
    obj = storage.get_s3_object(key)
    body = obj["Body"]

    def chunks() -> Iterator[bytes]:
        while data := body.read(1024 * 1024):
            yield data

    return StreamingResponse(
        chunks(),
        media_type=obj.get("ContentType") or content_type,
        headers={"Content-Length": str(obj.get("ContentLength") or "")},
    )
