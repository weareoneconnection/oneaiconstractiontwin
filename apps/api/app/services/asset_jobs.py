from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from app.core.time import utcnow as _utcnow
from typing import Any

from sqlalchemy import func, true
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.version import PIPELINE_VERSION
from app.core.security import RequestContext
from app.domain.models import (
    AssetBuildJob,
    AssetBuildPartition,
    AssetCacheEntry,
    AssetJobEvent,
    Document,
    TwinEntity,
)
from app.services.object_storage import storage
from app.services.asset_metrics import ASSET_CACHE_HITS, ASSET_JOBS_CREATED
from app.services.worker_signal import notify_workers

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "planning", "running", "finalizing"}


def utcnow() -> datetime:
    return _utcnow()


def normalize_options(options: dict[str, Any]) -> dict[str, Any]:
    compression = str(options.get("compression") or settings.asset_compression).lower()
    if compression not in {"none", "auto", "meshopt", "draco"}:
        raise ValueError("compression must be none, auto, meshopt or draco")
    return {
        "longitude": float(options.get("longitude", 101.6869)),
        "latitude": float(options.get("latitude", 3.1390)),
        "height": float(options.get("height", 0.0)),
        "partition_max_entities": max(1, min(int(options.get("partition_max_entities") or settings.asset_partition_max_entities), 1000)),
        "partition_max_triangles": max(1_000, int(options.get("partition_max_triangles") or settings.asset_partition_max_triangles)),
        "max_triangles_per_entity": max(1_000, int(options.get("max_triangles_per_entity") or settings.asset_max_triangles_per_entity)),
        "compression": compression,
    }


def build_cache_key(tenant_id: str, project_id: str, document_id: str, source_sha256: str, options: dict[str, Any]) -> str:
    payload = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "document_id": document_id,
        "source_sha256": source_sha256,
        "pipeline_version": PIPELINE_VERSION,
        "options": normalize_options(options),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def job_to_dict(job: AssetBuildJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "document_id": job.document_id,
        "status": job.status,
        "phase": job.phase,
        "progress": round(float(job.progress or 0), 2),
        "options": job.options or {},
        "source_sha256": job.source_sha256,
        "cache_key": job.cache_key,
        "cache_hit": bool(job.cache_hit),
        "total_partitions": int(job.total_partitions or 0),
        "completed_partitions": int(job.completed_partitions or 0),
        "checkpoint": job.checkpoint or {},
        "manifest_key": job.result_manifest_key,
        "manifest_url": job.result_manifest_url,
        "error": job.error,
        "cancel_requested": bool(job.cancel_requested),
        "attempts": int(job.attempts or 0),
        "worker_id": job.worker_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
    }


def partition_to_dict(row: AssetBuildPartition) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "partition_index": row.partition_index,
        "status": row.status,
        "entity_count": len(row.entity_ids or []),
        "estimated_triangles": row.estimated_triangles,
        "progress": row.progress,
        "attempts": row.attempts,
        "worker_id": row.worker_id,
        "error": row.error,
        "output": row.output or {},
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


def emit_event(
    db: Session,
    job: AssetBuildJob,
    event_type: str,
    message: str,
    progress: float | None = None,
    payload: dict[str, Any] | None = None,
) -> AssetJobEvent:
    seq = db.query(func.max(AssetJobEvent.sequence)).filter(AssetJobEvent.job_id == job.id).scalar() or 0
    event = AssetJobEvent(
        job_id=job.id,
        sequence=int(seq) + 1,
        event_type=event_type,
        message=message,
        progress=float(job.progress if progress is None else progress),
        payload=payload or {},
    )
    db.add(event)
    return event


def _document(db: Session, ctx: RequestContext, project_id: str, document_id: str) -> Document:
    row = db.query(Document).filter(
        Document.id == document_id,
        Document.project_id == project_id,
        Document.tenant_id == ctx.tenant_id,
        Document.organization_id == ctx.organization_id,
        Document.doc_type == "ifc_model",
    ).first()
    if not row:
        raise ValueError("IFC model not found")
    return row


def create_job(
    db: Session,
    ctx: RequestContext,
    project_id: str,
    document_id: str,
    options: dict[str, Any],
    force_rebuild: bool = False,
) -> tuple[AssetBuildJob, bool]:
    doc = _document(db, ctx, project_id, document_id)
    normalized = normalize_options(options)
    source_sha = str((doc.meta or {}).get("sha256") or "")
    if not source_sha:
        source_key = (doc.meta or {}).get("source_object_key")
        if source_key:
            source_sha = hashlib.sha256(storage.read_bytes(source_key)).hexdigest()
        else:
            source_sha = hashlib.sha256(open(doc.uri, "rb").read()).hexdigest()
    cache_key = build_cache_key(ctx.tenant_id, project_id, document_id, source_sha, normalized)

    if not force_rebuild:
        active = db.query(AssetBuildJob).filter(
            AssetBuildJob.tenant_id == ctx.tenant_id,
            AssetBuildJob.cache_key == cache_key,
            AssetBuildJob.status.in_(ACTIVE_STATUSES),
        ).order_by(AssetBuildJob.created_at.desc()).first()
        if active:
            return active, True

        cache = db.query(AssetCacheEntry).filter(
            AssetCacheEntry.cache_key == cache_key,
            AssetCacheEntry.tenant_id == ctx.tenant_id,
            AssetCacheEntry.status == "ready",
        ).first()
        if cache and cache.manifest_key and storage.exists(cache.manifest_key):
            cache.ref_count = int(cache.ref_count or 0) + 1
            cache.last_accessed_at = utcnow()
            job = AssetBuildJob(
                tenant_id=ctx.tenant_id,
                organization_id=ctx.organization_id,
                project_id=project_id,
                document_id=document_id,
                status="completed",
                phase="cache-hit",
                progress=100.0,
                options=normalized,
                source_sha256=source_sha,
                cache_key=cache_key,
                cache_hit=True,
                result_manifest_key=cache.manifest_key,
                result_manifest_url=storage.api_url(cache.manifest_key),
                completed_at=utcnow(),
                checkpoint={"cache_hit": True},
            )
            db.add(job); db.flush()
            ASSET_CACHE_HITS.inc()
            emit_event(db, job, "cache.hit", "Reused content-addressed streaming assets", 100.0, {"cache_key": cache_key})
            db.commit(); db.refresh(job)
            return job, False

    if force_rebuild:
        cache = db.query(AssetCacheEntry).filter(AssetCacheEntry.cache_key == cache_key).first()
        if cache:
            cache.status = "building"
            cache.manifest_key = None
            cache.size_bytes = 0
            cache.meta = {**(cache.meta or {}), "forced_rebuild_at": utcnow().isoformat()}

    job = AssetBuildJob(
        tenant_id=ctx.tenant_id,
        organization_id=ctx.organization_id,
        project_id=project_id,
        document_id=document_id,
        status="queued",
        phase="queued",
        progress=0.0,
        options=normalized,
        source_sha256=source_sha,
        cache_key=cache_key,
        attempts=0,
    )
    db.add(job); db.flush()
    ASSET_JOBS_CREATED.inc()
    emit_event(db, job, "job.queued", "Distributed asset build queued", 0.0, {"cache_key": cache_key})
    db.commit(); db.refresh(job)
    notify_workers(max(1, min(normalized["partition_max_entities"], 8)))
    return job, False


def get_job(db: Session, ctx: RequestContext, job_id: str) -> AssetBuildJob | None:
    return db.query(AssetBuildJob).filter(
        AssetBuildJob.id == job_id,
        AssetBuildJob.tenant_id == ctx.tenant_id,
        AssetBuildJob.organization_id == ctx.organization_id,
    ).first()


def list_jobs(db: Session, ctx: RequestContext, project_id: str, document_id: str | None = None, limit: int = 50) -> list[AssetBuildJob]:
    q = db.query(AssetBuildJob).filter(
        AssetBuildJob.project_id == project_id,
        AssetBuildJob.tenant_id == ctx.tenant_id,
        AssetBuildJob.organization_id == ctx.organization_id,
    )
    if document_id:
        q = q.filter(AssetBuildJob.document_id == document_id)
    return q.order_by(AssetBuildJob.created_at.desc()).limit(max(1, min(limit, 200))).all()


def list_partitions(db: Session, job_id: str) -> list[AssetBuildPartition]:
    return db.query(AssetBuildPartition).filter(AssetBuildPartition.job_id == job_id).order_by(AssetBuildPartition.partition_index).all()


def list_events(db: Session, job_id: str, after_sequence: int = 0) -> list[AssetJobEvent]:
    return db.query(AssetJobEvent).filter(
        AssetJobEvent.job_id == job_id,
        AssetJobEvent.sequence > after_sequence,
    ).order_by(AssetJobEvent.sequence).all()


def cancel_job(db: Session, ctx: RequestContext, job_id: str) -> AssetBuildJob:
    job = get_job(db, ctx, job_id)
    if not job:
        raise ValueError("Asset job not found")
    if job.status in TERMINAL_STATUSES:
        return job
    job.cancel_requested = True
    if job.status == "queued":
        job.status = "cancelled"
        job.phase = "cancelled"
        job.completed_at = utcnow()
        job.progress = 0.0
        parts = db.query(AssetBuildPartition).filter(AssetBuildPartition.job_id == job.id).all()
        for part in parts:
            if part.status == "queued":
                part.status = "cancelled"
        emit_event(db, job, "job.cancelled", "Queued build cancelled", job.progress)
    else:
        emit_event(db, job, "job.cancel-requested", "Cancellation requested; active workers will stop at a safe checkpoint", job.progress)
    db.commit(); db.refresh(job)
    notify_workers(1)
    return job


def resume_job(db: Session, ctx: RequestContext, job_id: str) -> AssetBuildJob:
    job = get_job(db, ctx, job_id)
    if not job:
        raise ValueError("Asset job not found")
    if job.status not in {"failed", "cancelled"}:
        raise ValueError("Only failed or cancelled jobs can be resumed")
    parts = list_partitions(db, job.id)
    for part in parts:
        if part.status in {"failed", "cancelled", "running"}:
            part.status = "queued"
            part.error = None
            part.worker_id = None
            part.lease_expires_at = None
            part.progress = 0.0
    job.cancel_requested = False
    job.error = None
    job.worker_id = None
    job.lease_expires_at = None
    job.completed_at = None
    job.attempts = int(job.attempts or 0) + 1
    job.completed_partitions = sum(1 for part in parts if part.status == "completed")
    job.status = "running" if parts else "queued"
    job.phase = "resumed" if parts else "queued"
    job.progress = 10.0 + 80.0 * (job.completed_partitions / max(1, len(parts))) if parts else 0.0
    emit_event(db, job, "job.resumed", "Resumable asset build returned to the durable queue", job.progress)
    db.commit(); db.refresh(job)
    notify_workers(max(1, len(parts)))
    return job


def recover_stale_leases(db: Session) -> int:
    now = utcnow()
    recovered = 0
    jobs = db.query(AssetBuildJob).filter(
        AssetBuildJob.status == "planning",
        AssetBuildJob.lease_expires_at.is_not(None),
        AssetBuildJob.lease_expires_at < now,
    ).all()
    for job in jobs:
        job.status = "queued"
        job.phase = "recovered"
        job.worker_id = None
        job.lease_expires_at = None
        emit_event(db, job, "lease.recovered", "Recovered stale planning lease", job.progress)
        recovered += 1

    parts = db.query(AssetBuildPartition).filter(
        AssetBuildPartition.status == "running",
        AssetBuildPartition.lease_expires_at.is_not(None),
        AssetBuildPartition.lease_expires_at < now,
    ).all()
    for part in parts:
        job = db.query(AssetBuildJob).filter(AssetBuildJob.id == part.job_id).first()
        if int(part.attempts or 0) >= settings.asset_job_max_attempts:
            part.status = "failed"
            part.error = "Worker lease expired too many times"
            if job:
                job.status = "failed"; job.phase = "partition-failed"; job.error = part.error
                emit_event(db, job, "partition.failed", part.error, job.progress, {"partition": part.partition_index})
        else:
            part.status = "queued"
            part.worker_id = None
            part.lease_expires_at = None
            if job:
                emit_event(db, job, "lease.recovered", "Recovered stale partition lease", job.progress, {"partition": part.partition_index})
        recovered += 1
    cancelling = db.query(AssetBuildJob).filter(
        AssetBuildJob.cancel_requested.is_(True),
        AssetBuildJob.status.in_({"queued", "planning", "running", "finalizing"}),
    ).all()
    for job in cancelling:
        running_parts = db.query(AssetBuildPartition).filter(
            AssetBuildPartition.job_id == job.id,
            AssetBuildPartition.status == "running",
        ).count()
        if running_parts:
            continue
        queued_parts = db.query(AssetBuildPartition).filter(
            AssetBuildPartition.job_id == job.id,
            AssetBuildPartition.status.in_({"queued", "failed"}),
        ).all()
        for part in queued_parts:
            part.status = "cancelled"
            part.completed_at = now
        job.status = "cancelled"
        job.phase = "cancelled"
        job.completed_at = now
        job.worker_id = None
        job.lease_expires_at = None
        emit_event(db, job, "job.cancelled", "Cancellation finalized at a durable checkpoint", job.progress)
        recovered += 1
    if recovered:
        db.commit()
    return recovered


def _model_document_criterion(db: Session, document_id: str):
    """Push the `external_ids.modelDocumentId` filter into SQL, portably.

    `.astext` belongs to PostgreSQL's own JSON/JSONB types; this column is the generic
    JSON type, where it does not exist. `.as_string()` is the portable spelling and
    compiles to `->>` on PostgreSQL and `JSON_EXTRACT` on SQLite. Dialects without JSON
    support fall back to the Python-side filter in plan_job.
    """
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect in {"postgresql", "sqlite", "mysql", "mariadb"}:
        return TwinEntity.external_ids["modelDocumentId"].as_string() == document_id
    return true()


def _with_skip_locked(query, db: Session):
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return query.with_for_update(skip_locked=True)
    return query


def claim_job_for_planning(db: Session, worker_id: str) -> AssetBuildJob | None:
    query = db.query(AssetBuildJob).filter(AssetBuildJob.status == "queued", AssetBuildJob.cancel_requested.is_(False)).order_by(AssetBuildJob.created_at)
    job = _with_skip_locked(query, db).first()
    if not job:
        return None
    job.status = "planning"
    job.phase = "partition-planning"
    job.worker_id = worker_id
    job.started_at = job.started_at or utcnow()
    job.lease_expires_at = utcnow() + timedelta(seconds=settings.asset_worker_lease_seconds)
    job.attempts = int(job.attempts or 0) + 1
    emit_event(db, job, "job.planning", "Planning resumable IFC partitions", 2.0, {"worker_id": worker_id})
    job.progress = 2.0
    db.commit(); db.refresh(job)
    return job


def estimate_entity_triangles(entity: TwinEntity) -> int:
    intel = entity.intelligence or {}
    ext = entity.external_ids or {}
    known = intel.get("geometryTriangles") or ext.get("triangleCount")
    if known:
        try:
            return max(12, int(known))
        except (TypeError, ValueError):
            pass
    typ = str(ext.get("ifcType") or "").upper()
    if any(x in typ for x in ("SLAB", "WALL", "ROOF", "STAIR")):
        return 12_000
    if any(x in typ for x in ("FLOW", "FURNISHING", "ASSEMBLY")):
        return 20_000
    return 4_000


def plan_job(db: Session, job_id: str, worker_id: str) -> AssetBuildJob:
    job = db.query(AssetBuildJob).filter(AssetBuildJob.id == job_id).first()
    if not job:
        raise ValueError("Asset job not found")
    if job.cancel_requested:
        job.status = "cancelled"; job.phase = "cancelled"; job.completed_at = utcnow()
        emit_event(db, job, "job.cancelled", "Build cancelled during planning", job.progress)
        db.commit(); return job

    existing = db.query(AssetBuildPartition).filter(AssetBuildPartition.job_id == job.id).count()
    if existing:
        job.total_partitions = existing
        job.completed_partitions = db.query(AssetBuildPartition).filter(AssetBuildPartition.job_id == job.id, AssetBuildPartition.status == "completed").count()
        job.status = "running"; job.phase = "partition-processing"; job.worker_id = None; job.lease_expires_at = None
        db.commit(); return job

    max_entities = int((job.options or {}).get("partition_max_entities") or settings.asset_partition_max_entities)
    max_triangles = int((job.options or {}).get("partition_max_triangles") or settings.asset_partition_max_triangles)

    # Multi-gigabyte models can hold hundreds of thousands of entities. The rows are
    # streamed (server-side batches) and partitions are written as they fill, so peak
    # memory is bounded by one partition rather than the whole model.
    query = (
        db.query(TwinEntity)
        .filter(
            TwinEntity.project_id == job.project_id,
            TwinEntity.tenant_id == job.tenant_id,
            _model_document_criterion(db, job.document_id),
        )
        .order_by(TwinEntity.created_at, TwinEntity.id)
    )

    partition_index = 0
    entity_count = 0
    ids: list[str] = []
    triangles = 0

    def flush_partition() -> None:
        nonlocal partition_index, ids, triangles
        if not ids:
            return
        db.add(AssetBuildPartition(
            job_id=job.id,
            partition_index=partition_index,
            status="queued",
            entity_ids=ids,
            estimated_triangles=triangles,
        ))
        partition_index += 1
        ids = []
        triangles = 0

    for entity in query.yield_per(1000):
        if (entity.external_ids or {}).get("modelDocumentId") != job.document_id:
            continue  # belt-and-braces for dialects without JSON extraction
        entity_count += 1
        estimate = estimate_entity_triangles(entity)
        if ids and (len(ids) >= max_entities or triangles + estimate > max_triangles):
            flush_partition()
        ids.append(entity.id)
        triangles += estimate
    flush_partition()

    if not entity_count:
        raise ValueError("No Twin Entities found for the IFC model")

    job.total_partitions = partition_index
    job.completed_partitions = 0
    job.status = "running"
    job.phase = "partition-processing"
    job.progress = 10.0
    job.worker_id = None
    job.lease_expires_at = None
    job.checkpoint = {"planned_entities": entity_count, "partitions": partition_index}
    emit_event(db, job, "job.partitioned", f"Planned {partition_index} durable partitions for {entity_count} entities", 10.0, {"partitions": partition_index, "entities": entity_count})
    db.commit(); db.refresh(job)
    notify_workers(max(1, partition_index))
    return job


def claim_partition(db: Session, worker_id: str) -> AssetBuildPartition | None:
    query = db.query(AssetBuildPartition).join(AssetBuildJob, AssetBuildJob.id == AssetBuildPartition.job_id).filter(
        AssetBuildPartition.status == "queued",
        AssetBuildJob.status == "running",
        AssetBuildJob.cancel_requested.is_(False),
    ).order_by(AssetBuildPartition.created_at, AssetBuildPartition.partition_index)
    part = _with_skip_locked(query, db).first()
    if not part:
        return None
    part.status = "running"
    part.worker_id = worker_id
    part.started_at = part.started_at or utcnow()
    part.lease_expires_at = utcnow() + timedelta(seconds=settings.asset_worker_lease_seconds)
    part.attempts = int(part.attempts or 0) + 1
    job = db.query(AssetBuildJob).filter(AssetBuildJob.id == part.job_id).first()
    if job:
        emit_event(db, job, "partition.started", f"Partition {part.partition_index + 1}/{job.total_partitions} started", job.progress, {"partition": part.partition_index, "worker_id": worker_id})
    db.commit(); db.refresh(part)
    return part


def claim_job_for_finalization(db: Session, worker_id: str) -> AssetBuildJob | None:
    query = db.query(AssetBuildJob).filter(
        AssetBuildJob.status == "running",
        AssetBuildJob.total_partitions > 0,
        AssetBuildJob.completed_partitions >= AssetBuildJob.total_partitions,
        AssetBuildJob.cancel_requested.is_(False),
    ).order_by(AssetBuildJob.updated_at)
    job = _with_skip_locked(query, db).first()
    if not job:
        return None
    job.status = "finalizing"
    job.phase = "finalizing-manifest"
    job.worker_id = worker_id
    job.lease_expires_at = utcnow() + timedelta(seconds=settings.asset_worker_lease_seconds)
    job.progress = max(job.progress, 92.0)
    emit_event(db, job, "job.finalizing", "Combining partition outputs into the final 3D Tiles manifest", job.progress, {"worker_id": worker_id})
    db.commit(); db.refresh(job)
    return job
