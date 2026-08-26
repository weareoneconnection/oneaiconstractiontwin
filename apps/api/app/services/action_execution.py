"""The last mile: carrying an approved action out of the twin and back again.

The twin sees, reasons and proposes; a human approves; OneClaw acts. This module
is the seam between the second and third of those, and it holds one invariant:

    the twin never claims an action happened unless the executor said so.

So dispatch and confirmation are separate states. `dispatched` means the action
left this system and has not been confirmed — a condition an operator can see and
reconcile, rather than one that looks identical to success.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import RequestContext
from app.core.time import utcnow
from app.domain.models import AgentAction, Evidence, Project
from app.integrations.oneai import OneClawAdapter
from app.services.audit import audit
from app.services.events import emit
from app.services.realtime import hub

log = logging.getLogger(__name__)

oneclaw = OneClawAdapter()

#: Terminal states. A report against one of these is ignored rather than applied,
#: which is what makes the executor's retries safe.
TERMINAL_STATUSES = {"executed", "failed"}

VALID_OUTCOMES = {"executed", "failed", "dry_run"}


class ActionNotFound(Exception):
    pass


class ActionNotDispatchable(Exception):
    """The action exists but is not in a state where this operation is legitimate."""


def _load(db: Session, ctx: RequestContext, action_id: str) -> AgentAction:
    row = db.scalar(
        select(AgentAction).where(
            AgentAction.id == action_id,
            AgentAction.tenant_id == ctx.tenant_id,
            AgentAction.organization_id == ctx.organization_id,
        )
    )
    if not row:
        raise ActionNotFound(f"Action {action_id} not found")
    return row


def normalize_recipients(raw: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate a distribution list and say precisely what is wrong with it.

    Resolving a role to a person is this system's job, not the executor's: the
    twin holds the project organisation, and OneClaw should never need a copy of
    it. By the time a list reaches the executor it is addresses only.
    """
    recipients: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            errors.append(f"recipient[{index}] must be an object")
            continue
        kind = str(entry.get("kind") or ("telegram" if entry.get("chatId") else "email")).strip().lower()
        address = str(entry.get("address") or entry.get("email") or entry.get("chatId") or "").strip()
        if not address:
            errors.append(f"recipient[{index}] has no address")
            continue
        if kind not in {"email", "telegram"}:
            errors.append(f"recipient[{index}] has unsupported channel '{kind}'")
            continue
        if kind == "email" and ("@" not in address or " " in address):
            errors.append(f"recipient[{index}] address '{address}' is not an email address")
            continue
        recipients.append(
            {
                "kind": kind,
                "address": address,
                "name": str(entry.get("name") or address),
                "role": str(entry.get("role") or ""),
            }
        )
    return recipients, errors


def _compose(project: Project, action: AgentAction) -> tuple[str, str]:
    """Build the message from the recommendation, without adding to it.

    Everything in the body is copied from the stored recommendation and its
    grounding. This is a notification about a decision that has already been
    made and recorded; it is not the place to introduce a new claim.
    """
    payload = action.payload or {}
    recommendation = str(payload.get("recommendation") or "").strip()
    grounded = payload.get("grounded_in") or {}
    target = grounded.get("target_activity")

    subject = f"[{project.code}] {project.name} · approved action {action.id}"
    if target:
        subject = f"[{project.code}] {target} · approved mitigation ({action.id})"

    lines = [
        f"Project: {project.name} ({project.code})",
        f"Action: {action.id} · proposed by {action.agent} · approved by {action.approved_by}",
        "",
        "APPROVED MITIGATION",
        recommendation or "(the stored recommendation is empty)",
        "",
        "GROUNDED IN",
        f"  Activities measured: {grounded.get('activities_measured', 'unknown')}",
        f"  Activities behind plan: {grounded.get('late_activities', 'unknown')}",
        f"  Critical activities behind plan: {grounded.get('critical_late_activities', 'unknown')}",
    ]
    if target:
        lines.append(f"  Target activity: {target}")
    lines += [
        "",
        "This message was sent by Construction Twin because a human approved this action.",
        "The twin proposed it; it did not decide it. Reply to the approver, not to this address.",
    ]
    return subject, "\n".join(lines)


def dispatch_action(
    db: Session,
    ctx: RequestContext,
    action_id: str,
    recipients: list[dict[str, Any]] | None,
    attachments: list[dict[str, Any]] | None = None,
) -> AgentAction:
    """Hand an approved action to OneClaw for delivery.

    Refusals are recorded on the action rather than raised past the caller where
    the approval itself would look like it failed: the approval is valid and
    stays valid, and the reason delivery did not happen is kept with it.
    """
    action = _load(db, ctx, action_id)

    if action.status in TERMINAL_STATUSES:
        raise ActionNotDispatchable(f"Action {action_id} is already {action.status}")
    if action.status == "dispatched":
        raise ActionNotDispatchable(f"Action {action_id} is already with the executor")
    if action.status != "approved" or not action.approved_by:
        raise ActionNotDispatchable("Only an approved action can be dispatched")

    clean, errors = normalize_recipients(recipients)
    if errors:
        raise ValueError("; ".join(errors))
    if not clean:
        raise ValueError("At least one recipient is required to dispatch an action")

    project = db.scalar(
        select(Project).where(
            Project.id == action.project_id,
            Project.tenant_id == ctx.tenant_id,
            Project.organization_id == ctx.organization_id,
        )
    )
    if not project:
        raise ActionNotFound("The action's project no longer exists")

    subject, body = _compose(project, action)
    summary = f"Notified {len(clean)} recipient(s) of approved action {action.id}"

    # The intent is committed before the call, not after it.
    #
    # OneClaw runs its inline queue inside the dispatch request, so the executor's
    # callback can land before this function returns. Writing `dispatched` after
    # the call therefore overwrote an already-reported `executed` with stale state
    # and left a delivered action looking unconfirmed. Recording the intent first
    # also means a crash mid-send leaves evidence that something was sent, which
    # is the whole reason this state exists.
    before = {"status": action.status}
    action.status = "dispatched"
    action.executor = "oneclaw"
    action.dispatched_at = utcnow()
    action.execution_error = None
    action.execution_result = {"stage": "dispatch", "recipients": clean}
    audit(
        db, ctx, "agent_action.dispatch", "agent_action", action.id, action.project_id,
        before=before,
        after={"status": action.status, "executor": "oneclaw", "recipient_count": len(clean)},
    )
    emit(db, "action.dispatched", "agent_action", action.id, {"project_id": action.project_id})
    db.commit()
    hub.publish(ctx.tenant_id, action.project_id, "action.dispatched",
                {"id": action.id, "status": "dispatched"})

    # Synchronous on purpose. This runs inside a FastAPI sync endpoint, which
    # Starlette executes on an anyio worker thread; asyncio.run there builds an
    # event loop with no working networking and the dispatch fails with an empty
    # error. The sync client has no loop to misplace. See OneClawAdapter.
    result = oneclaw.dispatch_notification_sync(
        action_id=action.id,
        project_id=action.project_id,
        approved_by=str(action.approved_by),
        subject=subject,
        body=body,
        recipients=clean,
        summary=summary,
        attachments=attachments or [],
    )

    # The callback may already have advanced this action while the call was in
    # flight. Re-read it and refuse to move a reported outcome backwards.
    db.expire_all()
    action = _load(db, ctx, action_id)
    reported = action.status in TERMINAL_STATUSES

    if not result.get("dispatched"):
        reason = str(result.get("reason") or "OneClaw refused the dispatch")
        if reported:
            # It was refused and yet something reported an outcome: the report is
            # the executor's own account of what happened, so it wins.
            log.warning("Dispatch of %s was refused (%s) but it is already %s", action.id, reason, action.status)
            return action
        action.status = "dispatch_failed"
        action.execution_error = reason
        action.execution_result = {"stage": "dispatch", "reason": reason}
        audit(
            db, ctx, "agent_action.dispatch_failed", "agent_action", action.id, action.project_id,
            before={"status": "dispatched"}, after={"status": action.status, "reason": reason},
        )
        emit(db, "action.dispatch_failed", "agent_action", action.id,
             {"project_id": action.project_id, "reason": reason})
        db.commit()
        db.refresh(action)
        hub.publish(ctx.tenant_id, action.project_id, "action.dispatch_failed",
                    {"id": action.id, "status": action.status, "reason": reason})
        log.warning("Dispatch refused for action %s: %s", action.id, reason)
        return action

    # Record the executor's task id whatever state the action reached, so a
    # reported action is still traceable to the run that produced it.
    action.executor_task_id = str(result.get("task_id") or "") or action.executor_task_id
    if not reported:
        action.execution_result = {
            **(action.execution_result or {}),
            "task_status": result.get("task_status"),
            "idempotent": bool(result.get("idempotent")),
        }
    db.commit()
    db.refresh(action)
    return action


def _evidence_hash(project_id: str, source_type: str, source_id: str, content: str) -> str:
    return hashlib.sha256(
        json.dumps([project_id, source_type, source_id, content], sort_keys=True).encode("utf-8")
    ).hexdigest()


def record_execution(
    db: Session,
    ctx: RequestContext,
    action_id: str,
    outcome: str,
    oneclaw_task_id: str | None,
    summary: str,
    receipts: Any,
    error: str | None,
    evidence: list[dict[str, Any]] | None,
) -> tuple[AgentAction, int]:
    """Apply the executor's report. Called only by the executor's own credential.

    A `dry_run` never becomes `executed`. That distinction is the whole point of
    the rehearsal mode: a chain that was exercised but delivered nothing must not
    leave a record saying the site was told.
    """
    outcome = str(outcome or "").strip().lower()
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"outcome must be one of: {', '.join(sorted(VALID_OUTCOMES))}")

    action = _load(db, ctx, action_id)

    if action.status in TERMINAL_STATUSES:
        # The executor retried a report that already landed. Accepting it again
        # would duplicate the evidence, so the stored record wins.
        log.info("Ignoring repeat execution report for %s (already %s)", action_id, action.status)
        return action, 0
    if action.status not in {"dispatched", "approved"}:
        raise ActionNotDispatchable(
            f"Action {action_id} is {action.status}; only a dispatched action can be reported on"
        )

    before = {"status": action.status}
    now = utcnow()

    if outcome == "executed":
        action.status = "executed"
        action.executed_at = now
        action.execution_error = None
    elif outcome == "failed":
        action.status = "failed"
        action.executed_at = now
        action.execution_error = error or summary or "The executor reported a failure"
    else:
        # A rehearsal leaves the action exactly where it was, and says so.
        action.status = "approved"
        action.dispatched_at = None
        action.execution_error = None

    action.executor = action.executor or "oneclaw"
    if oneclaw_task_id:
        action.executor_task_id = oneclaw_task_id
    action.execution_result = {
        "stage": "execution",
        "outcome": outcome,
        "summary": summary,
        "receipts": receipts,
        "reported_at": now.isoformat(),
    }

    created = 0
    for record in evidence or []:
        if not isinstance(record, dict):
            continue
        content = str(record.get("content") or "").strip()
        if not content:
            continue
        source_type = str(record.get("source_type") or "oneclaw_execution")
        source_id = str(record.get("source_id") or action.id)
        db.add(
            Evidence(
                tenant_id=ctx.tenant_id,
                organization_id=ctx.organization_id,
                project_id=action.project_id,
                source_type=source_type,
                source_id=source_id,
                content=content,
                # A delivery receipt is a fact about this system's own action, so
                # it carries full confidence; unlike a field observation, nothing
                # about it is inferred.
                confidence=1.0,
                fragment={"action_id": action.id, "outcome": outcome, **(record.get("metadata") or {})},
                hash=_evidence_hash(action.project_id, source_type, source_id, content),
            )
        )
        created += 1

    audit(
        db, ctx, "agent_action.execution_reported", "agent_action", action.id, action.project_id,
        before=before,
        after={"status": action.status, "outcome": outcome, "task_id": action.executor_task_id,
               "evidence_created": created},
        actor_type="machine",
        meta={"summary": summary, "error": error},
    )
    emit(db, f"action.{action.status}", "agent_action", action.id,
         {"project_id": action.project_id, "outcome": outcome})
    db.commit()
    db.refresh(action)
    hub.publish(ctx.tenant_id, action.project_id, f"action.{action.status}",
                {"id": action.id, "status": action.status, "outcome": outcome, "evidence_created": created})
    return action, created


def all_stale_dispatched_actions(db: Session) -> list[dict[str, Any]]:
    """Every tenant's unconfirmed actions, for the reconciliation job.

    Deliberately not tenant-scoped: this runs as a system job, and an operator
    asking "did anything we sent go unaccounted for" needs one answer across the
    estate, not one query per tenant they have to remember to run.
    """
    cutoff = utcnow() - timedelta(seconds=settings.oneclaw_dispatch_stale_after_seconds)
    rows = db.scalars(
        select(AgentAction)
        .where(AgentAction.status == "dispatched", AgentAction.dispatched_at < cutoff)
        .order_by(AgentAction.dispatched_at)
    ).all()
    return [
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "organization_id": row.organization_id,
            "project_id": row.project_id,
            "agent": row.agent,
            "approved_by": row.approved_by,
            "executor": row.executor,
            "executor_task_id": row.executor_task_id,
            "dispatched_at": row.dispatched_at,
            "unconfirmed_for_seconds": int((utcnow() - row.dispatched_at).total_seconds()) if row.dispatched_at else None,
        }
        for row in rows
    ]


def ingest_evidence(
    db: Session,
    ctx: RequestContext,
    project_id: str,
    records: list[dict[str, Any]],
) -> int:
    """File externally collected observations against a project.

    This is the reverse direction: the executor is not acting here, it is
    reporting something it saw. Confidence is deliberately below that of a
    delivery receipt — the twin observed the retrieval, not the fact itself, and
    an answer built on this should be able to tell the difference.
    """
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == ctx.tenant_id,
            Project.organization_id == ctx.organization_id,
        )
    )
    if not project:
        raise ActionNotFound(f"Project {project_id} not found")

    created = 0
    for record in records or []:
        content = str(record.get("content") or "").strip()
        if not content:
            continue
        source_type = str(record.get("source_type") or "external_observation")
        source_id = str(record.get("source_id") or "")
        digest = _evidence_hash(project_id, source_type, source_id, content)

        # The collector is expected to re-run on a schedule, and an unchanged
        # source must not accumulate a duplicate record on every pass.
        existing = db.scalar(
            select(Evidence).where(
                Evidence.tenant_id == ctx.tenant_id,
                Evidence.organization_id == ctx.organization_id,
                Evidence.project_id == project_id,
                Evidence.hash == digest,
            )
        )
        if existing:
            continue

        db.add(
            Evidence(
                tenant_id=ctx.tenant_id,
                organization_id=ctx.organization_id,
                project_id=project_id,
                source_type=source_type,
                source_id=source_id,
                content=content,
                confidence=0.8,
                fragment={"collected_by": "oneclaw", **(record.get("metadata") or {})},
                hash=digest,
            )
        )
        created += 1

    if created:
        audit(
            db, ctx, "evidence.ingest", "project", project_id, project_id,
            after={"created": created, "source": "oneclaw"},
            actor_type="machine",
        )
        emit(db, "evidence.ingested", "project", project_id, {"project_id": project_id, "created": created})
    db.commit()
    if created:
        hub.publish(ctx.tenant_id, project_id, "evidence.ingested", {"project_id": project_id, "created": created})
    return created


def stale_dispatched_actions(db: Session, ctx: RequestContext) -> list[dict[str, Any]]:
    """Actions that left for the executor and never came back.

    Surfacing these is the reason `dispatched` exists as a distinct state. An
    action nobody can account for is an operational fact, and hiding it inside
    'approved' would make the twin's own record misleading.
    """
    cutoff = utcnow() - timedelta(seconds=settings.oneclaw_dispatch_stale_after_seconds)
    rows = db.scalars(
        select(AgentAction).where(
            AgentAction.tenant_id == ctx.tenant_id,
            AgentAction.organization_id == ctx.organization_id,
            AgentAction.status == "dispatched",
            AgentAction.dispatched_at < cutoff,
        ).order_by(AgentAction.dispatched_at)
    ).all()
    return [
        {
            "id": row.id,
            "project_id": row.project_id,
            "agent": row.agent,
            "approved_by": row.approved_by,
            "executor": row.executor,
            "executor_task_id": row.executor_task_id,
            "dispatched_at": row.dispatched_at,
            "unconfirmed_for_seconds": int((utcnow() - row.dispatched_at).total_seconds()) if row.dispatched_at else None,
        }
        for row in rows
    ]
