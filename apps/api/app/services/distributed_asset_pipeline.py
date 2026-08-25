from __future__ import annotations

import json
import shutil
import time
import tempfile
from collections import Counter
from datetime import timedelta
from app.core.time import utc_iso
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, settings
from app.core.security import RequestContext
from app.db.base import SessionLocal
from app.domain.models import AssetBuildJob, AssetBuildPartition, AssetCacheEntry
from app.services.asset_jobs import (
    PIPELINE_VERSION,
    claim_job_for_finalization,
    claim_job_for_planning,
    claim_partition,
    emit_event,
    plan_job,
    recover_stale_leases,
    utcnow,
)
from app.services.asset_metrics import (ASSET_JOBS_COMPLETED, ASSET_JOBS_FAILED, ASSET_OUTPUT_BYTES, ASSET_PARTITIONS_COMPLETED, ASSET_PARTITION_SECONDS, ASSET_WORKER_LAST_CYCLE)
from app.services.asset_pipeline import _bbox, _box_volume, _decimate, _entity_mesh, _union_bbox, _write_glb
from app.services.geometry_service import geometry_for_model
from app.services.gltf_compression import compress_glb
from app.services.object_storage import storage
from app.services.worker_signal import notify_workers

DEFAULT_WORK_ROOT = PROJECT_ROOT / "data" / "asset-work"


def work_root() -> Path:
    # One definition of the scratch root, shared with the geometry service.
    root = settings.asset_work_path
    root.mkdir(parents=True, exist_ok=True)
    return root


def object_prefix(job: AssetBuildJob) -> str:
    return f"{settings.asset_object_prefix.strip('/')}/{job.tenant_id}/{job.cache_key}"


def _job_context(job: AssetBuildJob) -> RequestContext:
    return RequestContext(job.tenant_id, job.organization_id, "asset-worker", "platform_admin")


def _lod_chain(uri_prefix: str, entity_id: str, bbox: dict[str, list[float]]) -> dict[str, Any]:
    bv = {"box": _box_volume(bbox)}
    return {
        "boundingVolume": bv,
        "geometricError": 18.0,
        "refine": "REPLACE",
        "content": {"uri": f"{uri_prefix}/tiles/{entity_id}/lod2.glb"},
        "children": [{
            "boundingVolume": bv,
            "geometricError": 5.0,
            "refine": "REPLACE",
            "content": {"uri": f"{uri_prefix}/tiles/{entity_id}/lod1.glb"},
            "children": [{
                "boundingVolume": bv,
                "geometricError": 0.0,
                "content": {"uri": f"{uri_prefix}/tiles/{entity_id}/lod0.glb"},
            }],
        }],
    }


def process_partition(db: Session, partition_id: str, worker_id: str) -> AssetBuildPartition:
    part = db.query(AssetBuildPartition).filter(AssetBuildPartition.id == partition_id).first()
    if not part:
        raise ValueError("Asset partition not found")
    job = db.query(AssetBuildJob).filter(AssetBuildJob.id == part.job_id).first()
    if not job:
        raise ValueError("Asset build job not found")
    if job.cancel_requested:
        part.status = "cancelled"; part.completed_at = utcnow(); part.lease_expires_at = None
        job.status = "cancelled"; job.phase = "cancelled"; job.completed_at = utcnow()
        emit_event(db, job, "job.cancelled", "Build stopped at a partition checkpoint", job.progress, {"partition": part.partition_index})
        db.commit(); return part

    ctx = _job_context(job)
    opts = job.options or {}
    started_clock = time.monotonic()
    try:
        geom = geometry_for_model(
            db,
            ctx,
            job.project_id,
            job.document_id,
            entity_ids=set(part.entity_ids or []),
            max_triangles_per_entity=int(opts.get("max_triangles_per_entity") or settings.asset_max_triangles_per_entity),
        )
        if not geom.get("meshes"):
            raise ValueError("Partition geometry is empty")

        temp_root = work_root() / job.id / f"partition-{part.partition_index:05d}"
        if temp_root.exists():
            shutil.rmtree(temp_root)
        temp_root.mkdir(parents=True, exist_ok=True)
        prefix = object_prefix(job)
        relative_partition = f"partitions/{part.partition_index:05d}"
        records: list[dict[str, Any]] = []
        boxes: list[dict[str, list[float]]] = []
        total_bytes = 0
        compression_counts: Counter[str] = Counter()

        meshes = geom["meshes"]
        for mesh_index, mesh in enumerate(meshes):
            if job.cancel_requested:
                raise InterruptedError("Cancellation requested")
            entity_id = mesh["entity_id"]
            vertices, indices = _entity_mesh(mesh)
            bbox = _bbox(vertices); boxes.append(bbox)
            lods = []
            for level, factor in ((0, 1), (1, 2), (2, 4)):
                lod_indices = _decimate(indices, factor)
                rel = Path(relative_partition) / "tiles" / entity_id / f"lod{level}.glb"
                local = temp_root / rel.name
                stats = _write_glb(local, vertices, lod_indices, mesh.get("name") or entity_id)
                compression = compress_glb(local, str(opts.get("compression") or "none"))
                compression_counts[compression.get("applied", "none")] += 1
                object_key = f"{prefix}/{rel.as_posix()}"
                stored = storage.put_file(object_key, local, "model/gltf-binary")
                total_bytes += stored.size
                lods.append({
                    "level": level,
                    "uri": rel.as_posix(),
                    "object_key": stored.key,
                    "bytes": stored.size,
                    "triangles": stats["triangles"],
                    "vertices": stats["vertices"],
                    "bbox": bbox,
                    "compression": compression,
                })
            records.append({
                "entity_id": entity_id,
                "name": mesh.get("name"),
                "ifc_guid": mesh.get("ifc_guid"),
                "ifc_type": mesh.get("ifc_type"),
                "source_mode": mesh.get("mode"),
                "bbox": bbox,
                "lods": lods,
            })
            part.progress = round((mesh_index + 1) / max(1, len(meshes)) * 100.0, 2)
            part.lease_expires_at = utcnow() + timedelta(seconds=settings.asset_worker_lease_seconds)
            db.commit()

        partition_bbox = _union_bbox(boxes)
        part.output = {
            "partition_index": part.partition_index,
            "relative_prefix": relative_partition,
            "bbox": partition_bbox,
            "entity_count": len(records),
            "total_asset_bytes": total_bytes,
            "geometry_mode": geom.get("geometry_mode"),
            "compression": dict(compression_counts),
            "records": records,
        }
        part.status = "completed"
        part.progress = 100.0
        part.worker_id = worker_id
        part.lease_expires_at = None
        part.completed_at = utcnow()
        part.error = None

        completed = db.query(AssetBuildPartition).filter(
            AssetBuildPartition.job_id == job.id,
            AssetBuildPartition.status == "completed",
        ).count() + 1  # current row has not been flushed to a separate query view yet on every dialect
        completed = min(completed, int(job.total_partitions or completed))
        job.completed_partitions = completed
        job.progress = round(10.0 + 80.0 * completed / max(1, int(job.total_partitions or 1)), 2)
        job.phase = "partition-processing"
        job.checkpoint = {
            **(job.checkpoint or {}),
            "last_completed_partition": part.partition_index,
            "completed_partitions": completed,
        }
        emit_event(
            db,
            job,
            "partition.completed",
            f"Partition {part.partition_index + 1}/{job.total_partitions} completed",
            job.progress,
            {"partition": part.partition_index, "entities": len(records), "bytes": total_bytes},
        )
        db.commit(); db.refresh(part)
        ASSET_PARTITIONS_COMPLETED.inc()
        ASSET_PARTITION_SECONDS.observe(max(0.0, time.monotonic() - started_clock))
        ASSET_OUTPUT_BYTES.inc(total_bytes)
        shutil.rmtree(temp_root, ignore_errors=True)
        notify_workers(2)
        return part
    except InterruptedError:
        part.status = "cancelled"; part.error = "Cancellation requested"; part.lease_expires_at = None; part.completed_at = utcnow()
        job.status = "cancelled"; job.phase = "cancelled"; job.completed_at = utcnow()
        emit_event(db, job, "job.cancelled", "Build stopped at a safe partition checkpoint", job.progress, {"partition": part.partition_index})
        db.commit(); return part
    except Exception as exc:
        part.status = "failed"; part.error = str(exc); part.lease_expires_at = None; part.completed_at = utcnow()
        job.status = "failed"; job.phase = "partition-failed"; job.error = str(exc); job.completed_at = utcnow()
        ASSET_JOBS_FAILED.labels(phase="partition").inc()
        emit_event(db, job, "partition.failed", str(exc), job.progress, {"partition": part.partition_index, "attempts": part.attempts})
        db.commit()
        raise


def finalize_job(db: Session, job_id: str, worker_id: str) -> AssetBuildJob:
    job = db.query(AssetBuildJob).filter(AssetBuildJob.id == job_id).first()
    if not job:
        raise ValueError("Asset job not found")
    if job.cancel_requested:
        job.status = "cancelled"; job.phase = "cancelled"; job.completed_at = utcnow(); job.lease_expires_at = None
        emit_event(db, job, "job.cancelled", "Build cancelled before finalization", job.progress)
        db.commit(); return job

    partitions = db.query(AssetBuildPartition).filter(AssetBuildPartition.job_id == job.id).order_by(AssetBuildPartition.partition_index).all()
    if not partitions or any(p.status != "completed" for p in partitions):
        raise ValueError("Asset job is not ready for finalization")

    try:
        all_records: list[dict[str, Any]] = []
        partition_nodes: list[dict[str, Any]] = []
        boxes: list[dict[str, list[float]]] = []
        total_bytes = 0
        geometry_modes: Counter[str] = Counter()
        compression: Counter[str] = Counter()

        for part in partitions:
            output = part.output or {}
            bbox = output.get("bbox") or _bbox([])
            boxes.append(bbox)
            records = output.get("records") or []
            all_records.extend(records)
            total_bytes += int(output.get("total_asset_bytes") or 0)
            geometry_modes[str(output.get("geometry_mode") or "unknown")] += 1
            compression.update(output.get("compression") or {})
            rel_prefix = output.get("relative_prefix") or f"partitions/{part.partition_index:05d}"
            partition_nodes.append({
                "boundingVolume": {"box": _box_volume(bbox)},
                "geometricError": 120.0,
                "refine": "REPLACE",
                "children": [_lod_chain(rel_prefix, record["entity_id"], record["bbox"]) for record in records],
                "extras": {"oneai": {"partition_index": part.partition_index, "entity_count": len(records)}},
            })

        root_bbox = _union_bbox(boxes)
        opts = job.options or {}
        georef = {
            "longitude": float(opts.get("longitude", 0.0)),
            "latitude": float(opts.get("latitude", 0.0)),
            "height": float(opts.get("height", 0.0)),
        }
        prefix = object_prefix(job)
        tileset = {
            "asset": {"version": "1.1", "tilesetVersion": PIPELINE_VERSION},
            "geometricError": 500.0,
            "root": {
                "boundingVolume": {"box": _box_volume(root_bbox)},
                "geometricError": 240.0,
                "refine": "REPLACE",
                "children": partition_nodes,
            },
            "extras": {
                "oneai": {
                    "pipeline_version": PIPELINE_VERSION,
                    "job_id": job.id,
                    "project_id": job.project_id,
                    "model_document_id": job.document_id,
                    "cache_key": job.cache_key,
                    "georeference": georef,
                }
            },
        }
        tileset_key = f"{prefix}/tileset.json"
        storage.put_bytes(tileset_key, json.dumps(tileset, indent=2).encode(), "application/json")

        manifest = {
            "version": PIPELINE_VERSION,
            "pipeline": "distributed-content-addressed-3dtiles",
            "generated_at": utc_iso(),
            "job_id": job.id,
            "tenant_id": job.tenant_id,
            "project_id": job.project_id,
            "model_document_id": job.document_id,
            "source_sha256": job.source_sha256,
            "cache_key": job.cache_key,
            "cache_hit": False,
            "storage_backend": storage.backend,
            "format": "3D Tiles 1.1 + glTF 2.0 GLB",
            "partition_strategy": {
                "partition_count": len(partitions),
                "max_entities": opts.get("partition_max_entities"),
                "max_estimated_triangles": opts.get("partition_max_triangles"),
                "resumable": True,
            },
            "lod_strategy": "REPLACE hierarchy; LOD0 full, LOD1 ~50%, LOD2 ~25%",
            "compression_requested": opts.get("compression", "none"),
            "compression_applied": dict(compression),
            "geometry_modes": dict(geometry_modes),
            "georeference": georef,
            "root_bbox": root_bbox,
            "entity_count": len(all_records),
            "total_asset_bytes": total_bytes,
            "tileset_key": tileset_key,
            "tileset_url": storage.api_url(tileset_key),
            "object_prefix": prefix,
            "partitions": [{
                "index": p.partition_index,
                "entity_count": (p.output or {}).get("entity_count", 0),
                "bytes": (p.output or {}).get("total_asset_bytes", 0),
                "bbox": (p.output or {}).get("bbox"),
            } for p in partitions],
            "entities": all_records,
        }
        manifest_key = f"{prefix}/manifest.json"
        stored_manifest = storage.put_bytes(manifest_key, json.dumps(manifest, indent=2).encode(), "application/json")

        cache = db.query(AssetCacheEntry).filter(AssetCacheEntry.cache_key == job.cache_key).first()
        if not cache:
            cache = AssetCacheEntry(
                cache_key=job.cache_key,
                tenant_id=job.tenant_id,
                organization_id=job.organization_id,
                source_sha256=job.source_sha256,
            )
            db.add(cache)
        cache.pipeline_version = PIPELINE_VERSION
        cache.status = "ready"
        cache.manifest_key = manifest_key
        cache.size_bytes = total_bytes + stored_manifest.size
        cache.ref_count = int(cache.ref_count or 0) + 1
        cache.last_accessed_at = utcnow()
        cache.meta = {
            "project_id": job.project_id,
            "document_id": job.document_id,
            "tileset_key": tileset_key,
            "entity_count": len(all_records),
            "partition_count": len(partitions),
            "storage_backend": storage.backend,
        }

        job.status = "completed"
        job.phase = "completed"
        job.progress = 100.0
        job.completed_partitions = len(partitions)
        job.result_manifest_key = manifest_key
        job.result_manifest_url = storage.api_url(manifest_key)
        job.completed_at = utcnow()
        job.worker_id = worker_id
        job.lease_expires_at = None
        job.error = None
        job.checkpoint = {**(job.checkpoint or {}), "finalized": True, "manifest_key": manifest_key}
        emit_event(db, job, "job.completed", f"Distributed asset pipeline completed with {len(partitions)} partitions", 100.0, {"entity_count": len(all_records), "bytes": total_bytes, "cache_key": job.cache_key})
        db.commit(); db.refresh(job)
        ASSET_JOBS_COMPLETED.inc()
        return job
    except Exception as exc:
        job.status = "failed"; job.phase = "finalization-failed"; job.error = str(exc); job.completed_at = utcnow(); job.lease_expires_at = None
        ASSET_JOBS_FAILED.labels(phase="finalization").inc()
        emit_event(db, job, "job.failed", str(exc), job.progress)
        db.commit()
        raise


def fail_planning_job(db: Session, job: AssetBuildJob, exc: Exception) -> None:
    job.status = "failed"; job.phase = "planning-failed"; job.error = str(exc); job.completed_at = utcnow(); job.lease_expires_at = None
    ASSET_JOBS_FAILED.labels(phase="planning").inc()
    emit_event(db, job, "job.failed", str(exc), job.progress)
    db.commit()


def run_worker_cycle(worker_id: str) -> bool:
    """Run one durable unit of work. Safe to call from multiple processes."""
    ASSET_WORKER_LAST_CYCLE.labels(worker_id=worker_id).set(time.time())
    with SessionLocal() as db:
        recover_stale_leases(db)
        job = claim_job_for_planning(db, worker_id)
        if job:
            try:
                plan_job(db, job.id, worker_id)
            except Exception as exc:
                fresh = db.query(AssetBuildJob).filter(AssetBuildJob.id == job.id).first()
                if fresh:
                    fail_planning_job(db, fresh, exc)
            return True

    with SessionLocal() as db:
        part = claim_partition(db, worker_id)
        if part:
            try:
                process_partition(db, part.id, worker_id)
            except Exception:
                pass
            return True

    with SessionLocal() as db:
        job = claim_job_for_finalization(db, worker_id)
        if job:
            try:
                finalize_job(db, job.id, worker_id)
            except Exception:
                pass
            return True
    return False


def run_until_terminal(job_id: str, worker_id: str = "inline-test-worker", max_cycles: int = 1000) -> AssetBuildJob:
    """Test/local helper. Production should run `python -m app.workers.asset_worker`."""
    for _ in range(max_cycles):
        with SessionLocal() as db:
            job = db.query(AssetBuildJob).filter(AssetBuildJob.id == job_id).first()
            if job and job.status in {"completed", "failed", "cancelled"}:
                db.expunge(job)
                return job
        if not run_worker_cycle(worker_id):
            continue
    raise TimeoutError(f"Asset job {job_id} did not reach a terminal state")
