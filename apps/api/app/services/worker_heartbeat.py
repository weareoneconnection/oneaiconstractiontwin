from __future__ import annotations

from datetime import timedelta
from app.core.time import utcnow

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.models import WorkerHeartbeat


def record_worker_heartbeat(
    db: Session,
    worker_id: str,
    *,
    status: str = "online",
    worker_type: str = "asset",
    meta: dict | None = None,
) -> WorkerHeartbeat:
    now = utcnow()
    row = db.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id))
    if row is None:
        row = WorkerHeartbeat(
            worker_id=worker_id,
            worker_type=worker_type,
            status=status,
            version=settings.app_version,
            meta=meta or {},
            started_at=now,
            last_seen_at=now,
        )
        db.add(row)
    else:
        row.status = status
        row.version = settings.app_version
        row.meta = meta or row.meta or {}
        row.last_seen_at = now
    db.commit()
    db.refresh(row)
    return row


def active_workers(db: Session, worker_type: str = "asset") -> list[WorkerHeartbeat]:
    cutoff = utcnow() - timedelta(seconds=settings.worker_stale_after_seconds)
    return list(
        db.scalars(
            select(WorkerHeartbeat).where(
                WorkerHeartbeat.worker_type == worker_type,
                WorkerHeartbeat.status == "online",
                WorkerHeartbeat.last_seen_at >= cutoff,
            )
        ).all()
    )


def mark_worker_offline(db: Session, worker_id: str) -> None:
    row = db.scalar(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id))
    if row:
        row.status = "offline"
        row.last_seen_at = utcnow()
        db.commit()
