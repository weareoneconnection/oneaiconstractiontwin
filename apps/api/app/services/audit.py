"""Tamper-evident audit trail.

Every audit entry is chained to the previous entry of the same tenant with a
SHA-256 hash. The chain makes silent edits or deletions detectable: verifying it
recomputes each entry hash and confirms it matches the successor's `prev_hash`.

This is integrity evidence, not access control. A database administrator can
still rewrite history, but no longer without leaving a detectable break.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import RequestContext
from app.domain.models import AuditLog

GENESIS_HASH = "0" * 64


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(row: AuditLog) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "id": row.id,
                "sequence": int(row.sequence or 0),
                "prev_hash": row.prev_hash or GENESIS_HASH,
                "tenant_id": row.tenant_id,
                "organization_id": row.organization_id,
                "project_id": row.project_id,
                "actor_id": row.actor_id,
                "actor_type": row.actor_type,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "before": row.before or {},
                "after": row.after or {},
                "meta": row.meta or {},
                "created_at": row.created_at,
            }
        ).encode("utf-8")
    ).hexdigest()


def _tail(db: Session, tenant_id: str) -> AuditLog | None:
    max_sequence = db.scalar(
        select(func.max(AuditLog.sequence)).where(AuditLog.tenant_id == tenant_id)
    )
    if max_sequence is None:
        return None
    return db.scalar(
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id, AuditLog.sequence == max_sequence)
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )


def audit(
    db: Session,
    ctx: RequestContext,
    action: str,
    resource_type: str,
    resource_id: str,
    project_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    meta: dict | None = None,
    actor_type: str = "human",
) -> AuditLog:
    previous = _tail(db, ctx.tenant_id)
    row = AuditLog(
        sequence=(int(previous.sequence) + 1) if previous else 1,
        prev_hash=(previous.entry_hash or GENESIS_HASH) if previous else GENESIS_HASH,
        tenant_id=ctx.tenant_id,
        organization_id=ctx.organization_id,
        project_id=project_id,
        actor_id=ctx.user_id,
        actor_type="agent" if ctx.role == "ai_agent" else actor_type,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before=before or {},
        after=after or {},
        meta={**(meta or {}), "auth_source": ctx.auth_source},
    )
    db.add(row)
    db.flush()  # applies created_at default before the entry is hashed
    row.entry_hash = compute_entry_hash(row)
    db.flush()
    return row


def verify_audit_chain(db: Session, tenant_id: str, limit: int | None = None) -> dict[str, Any]:
    """Recompute the whole chain for a tenant and report the first break."""
    query = (
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.sequence, AuditLog.created_at)
    )
    if limit:
        query = query.limit(limit)
    all_rows = list(db.scalars(query).all())
    # Rows written before the chain existed (v0.7.0 databases) carry sequence 0 and
    # no hash. They are reported as unchained rather than folded into the chain,
    # which would claim protection they never had.
    legacy = [row for row in all_rows if int(row.sequence or 0) == 0 and not row.entry_hash]
    rows = [row for row in all_rows if row not in legacy]
    expected_prev = GENESIS_HASH
    expected_sequence = 1
    for row in rows:
        if (row.prev_hash or GENESIS_HASH) != expected_prev:
            return _broken(row, "prev_hash does not match the preceding entry", len(rows))
        if int(row.sequence or 0) != expected_sequence:
            return _broken(row, "sequence is not contiguous (an entry was removed)", len(rows))
        if compute_entry_hash(row) != (row.entry_hash or ""):
            return _broken(row, "entry content does not match its recorded hash", len(rows))
        expected_prev = row.entry_hash
        expected_sequence += 1
    return {
        "ok": True,
        "tenant_id": tenant_id,
        "entries": len(rows),
        "legacy_unchained_entries": len(legacy),
        "head_hash": expected_prev,
        "algorithm": "sha256-chain",
    }


def _broken(row: AuditLog, reason: str, total: int) -> dict[str, Any]:
    return {
        "ok": False,
        "tenant_id": row.tenant_id,
        "entries": total,
        "broken_at": {
            "id": row.id,
            "sequence": int(row.sequence or 0),
            "action": row.action,
            "created_at": row.created_at,
        },
        "reason": reason,
        "algorithm": "sha256-chain",
    }
