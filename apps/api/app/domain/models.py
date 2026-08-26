from __future__ import annotations
from datetime import datetime
from uuid import uuid4
from sqlalchemy import String, Float, DateTime, Text, JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
from app.core.time import utcnow


def uid() -> str:
    return str(uuid4())


class TenantScoped:
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Project(Base, TenantScoped):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(255), index=True)
    code: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active")
    planned_progress: Mapped[float] = mapped_column(Float, default=0)
    actual_progress: Mapped[float] = mapped_column(Float, default=0)
    forecast_delay_days: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TwinEntity(Base, TenantScoped):
    __tablename__ = "twin_entities"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    external_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    spatial: Mapped[dict] = mapped_column(JSON, default=dict)
    lifecycle: Mapped[dict] = mapped_column(JSON, default=dict)
    links: Mapped[dict] = mapped_column(JSON, default=dict)
    intelligence: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (Index("ix_twin_project_type", "project_id", "entity_type"),)


class Activity(Base, TenantScoped):
    __tablename__ = "activities"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    planned_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned_finish: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_finish: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    percent_complete: Mapped[float] = mapped_column(Float, default=0)
    total_float_days: Mapped[float] = mapped_column(Float, default=0)
    critical: Mapped[bool] = mapped_column(default=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class MappingRule(Base, TenantScoped):
    __tablename__ = "mapping_rules"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    source: Mapped[dict] = mapped_column(JSON, default=dict)
    target: Mapped[dict] = mapped_column(JSON, default=dict)
    strategy: Mapped[str] = mapped_column(String(32), default="manual")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class Document(Base, TenantScoped):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    uri: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base, TenantScoped):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    fragment: Mapped[dict] = mapped_column(JSON, default=dict)
    hash: Mapped[str] = mapped_column(String(128), default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Comment(Base, TenantScoped):
    """A note attached to a project or to something inside it.

    Comments are how a team records judgement the data cannot hold: why an activity
    slipped, whether an AI recommendation is sound, what was agreed on site. They are
    tenant-scoped like every other record, threaded one level deep, and resolvable so a
    discussion can be closed without deleting the history of it.
    """

    __tablename__ = "comments"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    #: What the comment is about: "project", "twin_entity", "activity", "risk",
    #: "agent_action". Kept as a loose pair rather than a foreign key so a comment can
    #: outlive the thing it discusses.
    target_type: Mapped[str] = mapped_column(String(64), default="project", index=True)
    target_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    author_id: Mapped[str] = mapped_column(String(64), index=True)
    author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_role: Mapped[str] = mapped_column(String(64), default="viewer")
    resolved: Mapped[bool] = mapped_column(default=False, index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        Index("ix_comment_project_target", "project_id", "target_type", "target_id"),
        Index("ix_comment_thread", "parent_id", "created_at"),
    )


class Risk(Base, TenantScoped):
    __tablename__ = "risks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    probability: Mapped[float] = mapped_column(Float)
    impact: Mapped[float] = mapped_column(Float)
    exposure: Mapped[float] = mapped_column(Float)
    causes: Mapped[list] = mapped_column(JSON, default=list)
    affected_entities: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    mitigations: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GraphRelation(Base, TenantScoped):
    __tablename__ = "graph_relations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    relation: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentAction(Base, TenantScoped):
    """An agent's proposal and, once a human approves it, its execution record.

    The status is a one-way progression:

        pending_approval → approved → dispatched → executed
                                    ↘ dispatch_failed
                                    ↘ failed

    `dispatched` is the state that matters most. It means the action left this
    system for the executor and has not been confirmed, which is a real and
    reportable condition — an action that was sent and never came back must be
    visible rather than indistinguishable from one that succeeded.
    """

    __tablename__ = "agent_actions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    agent: Mapped[str] = mapped_column(String(100))
    action_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending_approval", index=True)
    requested_by: Mapped[str] = mapped_column(String(64), default="agent")
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Execution, performed by OneClaw. This twin never writes these itself.
    executor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executor_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    execution_result: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    """Append-only, hash-chained audit record.

    Each entry stores the hash of the previous entry for the same tenant, so any
    edit or deletion inside the chain is detectable via /api/v1/admin/audit/verify.
    Application code never updates or deletes rows in this table.
    """

    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    sequence: Mapped[int] = mapped_column(default=0, index=True)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    entry_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(32), default="human")
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(64))
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("ix_audit_tenant_sequence", "tenant_id", "sequence"),)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    published: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AssetBuildJob(Base, TenantScoped):
    __tablename__ = "asset_build_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(String(64), ForeignKey("projects.id"), index=True)
    document_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(64), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    source_sha256: Mapped[str] = mapped_column(String(128), default="", index=True)
    cache_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    cache_hit: Mapped[bool] = mapped_column(default=False)
    total_partitions: Mapped[int] = mapped_column(default=0)
    completed_partitions: Mapped[int] = mapped_column(default=0)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    result_manifest_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_manifest_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(default=0)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (
        Index("ix_asset_job_status_created", "status", "created_at"),
        Index("ix_asset_job_project_document", "project_id", "document_id"),
    )


class AssetBuildPartition(Base):
    __tablename__ = "asset_build_partitions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("asset_build_jobs.id"), index=True)
    partition_index: Mapped[int] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    entity_ids: Mapped[list] = mapped_column(JSON, default=list)
    estimated_triangles: Mapped[int] = mapped_column(default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    attempts: Mapped[int] = mapped_column(default=0)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (
        Index("ix_asset_partition_job_index", "job_id", "partition_index"),
        Index("ix_asset_partition_status_created", "status", "created_at"),
    )


class AssetCacheEntry(Base, TenantScoped):
    __tablename__ = "asset_cache_entries"
    cache_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(128), index=True)
    pipeline_version: Mapped[str] = mapped_column(String(32), default="0.7.0")
    status: Mapped[str] = mapped_column(String(32), default="building", index=True)
    manifest_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(default=0)
    ref_count: Mapped[int] = mapped_column(default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AssetJobEvent(Base):
    __tablename__ = "asset_job_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("asset_build_jobs.id"), index=True)
    sequence: Mapped[int] = mapped_column(default=0)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (Index("ix_asset_job_event_job_sequence", "job_id", "sequence"),)



class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    worker_type: Mapped[str] = mapped_column(String(64), default="asset", index=True)
    status: Mapped[str] = mapped_column(String(32), default="online", index=True)
    version: Mapped[str] = mapped_column(String(32), default="0.7.0")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BackupRecord(Base):
    __tablename__ = "backup_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    backup_type: Mapped[str] = mapped_column(String(32), default="full")
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    database_artifact: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_artifact: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_artifact: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
