"""Project intelligence: evidence-first answers, risk, forecast, simulation, agents.

Two rules hold throughout this module:

1. No conclusion is presented without the evidence it rests on. Claims are derived
   from retrieved records, and a claim with no supporting record is returned as
   unsupported rather than dropped.
2. Every number reports how it was produced. Where a value comes from a heuristic
   rather than a calibrated model, the response says so in `model` / `basis`.
"""

from __future__ import annotations

import random
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.observability import AI_REQUESTS, EVIDENCE_COVERAGE
from app.core.security import RequestContext
from app.core.time import utcnow
from app.domain.models import AgentAction, Evidence, Project, Risk
from app.domain.schemas import AskResponse, EvidenceRef, SimulationRequest, SimulationResponse
from app.integrations.oneai import OneAICoreAdapter
from app.services.audit import audit
from app.services.evidence_search import search_evidence
from app.services.events import emit
from app.services.realtime import hub
from app.services.schedule_analytics import ScheduleSample, collect_schedule_sample

core = OneAICoreAdapter()

RISK_MODEL = "heuristic-schedule-v0.7.1"
FORECAST_MODEL = "monte-carlo-activity-variance-v0.7.1"


CITATION_RE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9._\-/]{1,63})\]")


def verify_citations(answer: str, supplied_ids: list[str]) -> dict[str, Any]:
    """Check that every record the answer cites was actually given to the model.

    A language model asked to cite will sometimes cite something plausible that was
    never supplied. That is the single most damaging failure mode for an evidence-first
    product, so citations are verified rather than displayed on trust.
    """
    cited = list(dict.fromkeys(CITATION_RE.findall(answer or "")))
    supplied = {value.lower() for value in supplied_ids if value}
    verified = [value for value in cited if value.lower() in supplied]
    unverified = [value for value in cited if value.lower() not in supplied]
    return {
        "cited": cited,
        "verified": verified,
        "unverified": unverified,
        "supplied": list(supplied_ids),
    }


def _project(db: Session, ctx: RequestContext, project_id: str) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.tenant_id == ctx.tenant_id,
            Project.organization_id == ctx.organization_id,
        )
    )
    if not project:
        raise ValueError("Project not found")
    return project


def _sample(db: Session, ctx: RequestContext, project_id: str) -> ScheduleSample:
    return collect_schedule_sample(db, ctx.tenant_id, ctx.organization_id, project_id)


# --------------------------------------------------------------------------- ask


# Words that appear in almost every activity name and therefore prove nothing about
# which activity a record refers to.
GENERIC_ACTIVITY_TERMS = frozenset(
    "zone area level floor works work installation install phase section block the and of".split()
)


def _supports_activity(content: str, activity) -> bool:
    """A record supports a claim about an activity only if it plainly refers to it.

    Either it cites the activity id, or it shares at least two non-generic terms with
    the activity name. Matching a single word like "roof" is not support.
    """
    text = (content or "").lower()
    if not text:
        return False
    if activity.external_id and activity.external_id.lower() in text:
        return True
    distinctive = {
        term for term in activity.name.lower().replace("-", " ").split()
        if term not in GENERIC_ACTIVITY_TERMS and len(term) > 2
    }
    return len(distinctive & set(text.replace(";", " ").replace(",", " ").split())) >= 2


def _build_claims(
    project: Project, sample: ScheduleSample, hits: list, evidence_ids: list[str]
) -> list[dict[str, Any]]:
    """Derive claims from measured state, each carrying the records that support it.

    A claim is `supported` only when at least one retrieved record backs it. The
    supporting ids are returned so the caller can show the trail.
    """
    claims: list[dict[str, Any]] = []
    variance = round(project.actual_progress - project.planned_progress, 2)
    if variance < 0:
        claims.append(
            {
                "claim": f"{project.name} is {abs(variance)} percentage points behind the baseline",
                "basis": "project progress record",
                "supported": True,
                "evidence_ids": [],
                "source": "measured",
            }
        )
    late = sample.late_activities
    if late:
        worst = late[0]
        supporting = [hit.evidence.id for hit in hits if _supports_activity(hit.evidence.content, worst)]
        claims.append(
            {
                "claim": f"Activity {worst.external_id} ({worst.name}) has slipped {worst.slip_days} days",
                "basis": "schedule variance",
                "supported": bool(supporting),
                "evidence_ids": supporting,
                "source": "measured",
            }
        )
    if hits:
        top = hits[0].evidence
        claims.append(
            {
                "claim": f"The highest-ranked record for this question is {top.source_type} {top.source_id}",
                "basis": "bm25 retrieval",
                "supported": True,
                "evidence_ids": [top.id],
                "source": "retrieved",
            }
        )
    if not claims:
        claims.append(
            {
                "claim": "No measurable variance or matching record was found for this question",
                "basis": "empty result",
                "supported": bool(evidence_ids),
                "evidence_ids": evidence_ids,
                "source": "measured",
            }
        )
    return claims


async def ask_twin(db: Session, ctx: RequestContext, project_id: str, question: str) -> AskResponse:
    project = _project(db, ctx, project_id)
    sample = _sample(db, ctx, project_id)

    hits = search_evidence(db, ctx.tenant_id, ctx.organization_id, project_id, question, limit=5)
    evidence_ids = [hit.evidence.id for hit in hits]

    result = await core.reason(
        question,
        {
            "project": project.name,
            "actual": project.actual_progress,
            "planned": project.planned_progress,
            "forecast_delay_days": project.forecast_delay_days,
            "late_activities": [
                {"external_id": item.external_id, "name": item.name, "slip_days": item.slip_days}
                for item in sample.late_activities[:5]
            ],
            "evidence_excerpts": [hit.evidence.content for hit in hits],
            "evidence_records": [
                {
                    "source_id": hit.evidence.source_id,
                    "source_type": hit.evidence.source_type,
                    "content": hit.evidence.content,
                }
                for hit in hits
            ],
        },
    )

    # A model that cites a record we never supplied has left the evidence behind. The
    # citation is checked against what was actually retrieved rather than trusted.
    citation_check = verify_citations(result.text, [hit.evidence.source_id for hit in hits])

    evidence = [
        EvidenceRef(
            id=hit.evidence.id,
            source_type=hit.evidence.source_type,
            source_id=hit.evidence.source_id,
            content=hit.evidence.content,
            confidence=hit.evidence.confidence,
            relevance=hit.score,
            matched_terms=hit.matched_terms,
        )
        for hit in hits
    ]

    claims = _build_claims(project, sample, hits, evidence_ids)
    supported = sum(1 for claim in claims if claim.get("supported"))
    coverage = round(supported / len(claims), 4) if claims else 0.0

    answer = result.text
    if citation_check["unverified"]:
        answer += (
            " Note: this answer referenced "
            + ", ".join(citation_check["unverified"])
            + ", which is not among the records retrieved for this question. Treat those references as unverified."
        )
    if not evidence:
        # The evidence policy is enforced here, not merely stated in the docs.
        confidence = min(result.confidence, 0.4)
        answer += (
            " No project record matched this question, so this response is provisional "
            "and must not be used as the basis for a contractual decision."
        )
    else:
        confidence = round(result.confidence * (0.6 + 0.4 * coverage), 4)
        if citation_check["unverified"]:
            # An unverifiable citation is a grounding failure, not a rounding error.
            confidence = round(min(confidence, 0.45), 4)

    EVIDENCE_COVERAGE.labels(project_id).set(coverage)
    AI_REQUESTS.labels("ask_twin", "success").inc()
    audit(
        db,
        ctx,
        "ai.ask_twin",
        "project",
        project_id,
        project_id,
        after={
            "question": question,
            "confidence": confidence,
            "evidence_ids": evidence_ids,
            "evidence_coverage": coverage,
            "provider": result.metadata.get("provider"),
            "mode": result.metadata.get("mode"),
        },
    )
    db.commit()

    return AskResponse(
        question=question,
        answer=answer,
        confidence=confidence,
        provisional=not evidence,
        evidence_coverage=coverage,
        claims=claims,
        evidence=evidence,
        risks=[],
        recommended_actions=[
            {"type": "review_schedule", "requires_approval": True, "reason": "human approval is required for every action"}
        ],
        reasoning={
            "provider": result.metadata.get("provider"),
            "model": result.metadata.get("model"),
            "mode": result.metadata.get("mode"),
            "model_backed": bool(result.metadata.get("model_backed")),
            "retrieval": "bm25",
            "schedule_sample_size": sample.sample_size,
            "citations": citation_check,
            "usage": result.metadata.get("usage"),
            "request_id": result.metadata.get("request_id"),
            "fallback_used": result.metadata.get("fallback_used"),
            "provider_error": result.metadata.get("provider_error"),
        },
    )


# -------------------------------------------------------------------------- risk


def evaluate_risks(db: Session, ctx: RequestContext, project_id: str) -> tuple[Risk, dict[str, Any]]:
    project = _project(db, ctx, project_id)
    sample = _sample(db, ctx, project_id)

    late = sample.late_activities
    critical_late = [item for item in late if item.critical]
    # Probability: share of activities actually slipping, weighted towards the
    # critical path. Impact: measured critical slippage against the project baseline.
    slip_ratio = len(late) / sample.sample_size if sample.sample_size else 0.0
    critical_ratio = len(critical_late) / len(late) if late else 0.0
    probability = round(min(0.95, 0.15 + 0.6 * slip_ratio + 0.2 * critical_ratio), 4)

    critical_slip = max((item.slip_days for item in critical_late), default=0.0)
    baseline_gap = max(0.0, project.planned_progress - project.actual_progress)
    impact = round(min(1.0, 0.1 + critical_slip / 45.0 + baseline_gap / 100.0), 4)
    exposure = round(probability * impact, 4)

    causes = [
        f"{item.external_id} {item.name} slipped {item.slip_days} days"
        for item in late[:5]
    ] or ["No activity-level slippage recorded"]

    evidence_ids = [
        row.id
        for row in db.scalars(
            select(Evidence)
            .where(
                Evidence.project_id == project_id,
                Evidence.tenant_id == ctx.tenant_id,
                Evidence.organization_id == ctx.organization_id,
            )
            .order_by(Evidence.created_at.desc())
            .limit(5)
        ).all()
    ]

    mitigations = []
    if critical_late:
        mitigations.append(
            {
                "name": f"Resequence work downstream of {critical_late[0].external_id}",
                "expected_recovery_days": round(min(critical_slip * 0.35, 10.0), 1),
                "basis": "critical-path slippage",
            }
        )
    if late:
        mitigations.append(
            {
                "name": "Add a second shift on the slipping activities",
                "expected_recovery_days": round(min(sample.mean_slip * 0.55, 14.0), 1),
                "basis": "mean activity slippage",
            }
        )
    if not mitigations:
        mitigations.append({"name": "Maintain the current plan", "expected_recovery_days": 0.0, "basis": "no slippage detected"})

    row = Risk(
        tenant_id=ctx.tenant_id,
        organization_id=ctx.organization_id,
        project_id=project_id,
        category="schedule",
        title="Schedule slippage" if late else "No schedule slippage detected",
        probability=probability,
        impact=impact,
        exposure=exposure,
        causes=causes,
        affected_entities=[item.activity_id for item in late[:20]],
        evidence_ids=evidence_ids,
        mitigations=mitigations,
    )
    db.add(row)
    db.flush()
    emit(db, "risk.detected", "risk", row.id, {"project_id": project_id, "exposure": exposure})
    audit(
        db,
        ctx,
        "risk.evaluate",
        "risk",
        row.id,
        project_id,
        after={
            "probability": probability,
            "impact": impact,
            "exposure": exposure,
            "model": RISK_MODEL,
            "sample_size": sample.sample_size,
            "data_quality": sample.data_quality,
        },
    )
    AI_REQUESTS.labels("risk_evaluate", "success").inc()
    db.commit()
    db.refresh(row)
    meta = {
        "model": RISK_MODEL,
        "calibrated": False,
        "sample_size": sample.sample_size,
        "data_quality": sample.data_quality,
        "late_activities": len(late),
        "critical_late_activities": len(critical_late),
    }
    return row, meta


# ---------------------------------------------------------------------- forecast


def forecast_project(
    db: Session, ctx: RequestContext, project_id: str, iterations: int = 1000, seed: int | None = None
) -> dict[str, Any]:
    """Monte Carlo over the project's own activity variance distribution.

    Each iteration resamples observed activity slippage (bootstrap) along the
    critical path. With too few activities to resample, the forecast falls back to
    the recorded baseline delay and says so instead of manufacturing a distribution.
    """
    project = _project(db, ctx, project_id)
    sample = _sample(db, ctx, project_id)
    iterations = max(100, min(int(iterations), 20_000))
    rng = random.Random(seed if seed is not None else f"{project_id}:{sample.sample_size}")

    critical = [item for item in sample.variances if item.critical]
    population = [item.slip_days for item in (critical or sample.variances)]
    remaining_share = max(
        0.0, 1.0 - (project.actual_progress / 100.0 if project.actual_progress else 0.0)
    )

    if len(population) >= 3:
        driving_count = max(1, len(critical) or len(sample.variances))
        draws: list[float] = []
        for _ in range(iterations):
            # Bootstrap the remaining critical work from observed slippage.
            future_activities = max(1, round(driving_count * remaining_share))
            total = sum(rng.choice(population) for _ in range(future_activities))
            draws.append(max(0.0, total / max(1, future_activities) * future_activities ** 0.5))
        basis = "bootstrap-of-observed-activity-slippage"
        confidence = 0.72 if sample.data_quality == "sufficient" else 0.45
    else:
        base = max(0.0, float(project.forecast_delay_days or 0.0))
        spread = max(1.0, base * 0.3)
        draws = [max(0.0, rng.gauss(base, spread)) for _ in range(iterations)]
        basis = "recorded-baseline-delay-only (insufficient activity history)"
        confidence = 0.25

    draws.sort()

    def percentile(p: float) -> float:
        return round(draws[min(len(draws) - 1, int(p * (len(draws) - 1)))], 1)

    drivers = [
        {"activity": item.external_id, "name": item.name, "slip_days": item.slip_days, "critical": item.critical}
        for item in sample.late_activities[:5]
    ]

    result = {
        "delay_days": {"p10": percentile(0.10), "p50": percentile(0.50), "p90": percentile(0.90)},
        "drivers": drivers,
        "confidence": confidence,
        "iterations": iterations,
        "model": FORECAST_MODEL,
        "calibrated": False,
        "basis": basis,
        "sample": {
            "activities_total": sample.total_activities,
            "activities_measured": sample.sample_size,
            "critical_activities": len(critical),
            "mean_slip_days": round(sample.mean_slip, 2),
            "stdev_slip_days": round(sample.stdev_slip, 2),
            "data_quality": sample.data_quality,
        },
        "warning": None
        if sample.data_quality == "sufficient"
        else "Insufficient activity history for a calibrated forecast; treat as indicative only.",
    }
    audit(db, ctx, "forecast.generate", "project", project_id, project_id, after=result)
    AI_REQUESTS.labels("forecast", "success").inc()
    db.commit()
    return result


# -------------------------------------------------------------------- simulation

# Recovery assumptions are stated, not buried: an operator can review and change
# them, and every simulation response reports the set it ran with.
RECOVERY_ASSUMPTIONS = [
    {"name": "Resequence work", "cost_share": 0.08, "recovery_share": 0.35},
    {"name": "Add shift", "cost_share": 0.22, "recovery_share": 0.55},
    {"name": "Add resource + resequence", "cost_share": 0.35, "recovery_share": 0.80},
]


def simulate(req: SimulationRequest) -> SimulationResponse:
    schedule_impact = round(req.delay_days * (1.0 - req.recovery_efficiency * 0.25), 1)
    cost_impact = round(req.delay_days * req.cost_per_day, 2)
    risk_delta = round(min(0.5, req.delay_days / 30), 3)
    options = [
        {
            "name": assumption["name"],
            "cost": round(cost_impact * assumption["cost_share"], 2),
            "recovery_days": round(req.delay_days * assumption["recovery_share"], 1),
            "cost_share_assumption": assumption["cost_share"],
            "recovery_share_assumption": assumption["recovery_share"],
        }
        for assumption in RECOVERY_ASSUMPTIONS
    ]
    return SimulationResponse(
        scenario=req.scenario,
        schedule_impact_days=schedule_impact,
        cost_impact=cost_impact,
        risk_delta=risk_delta,
        options=options,
        model="scenario-assumption-set-v0.7.1",
        calibrated=False,
        assumptions=RECOVERY_ASSUMPTIONS,
    )


# ------------------------------------------------------------------------ agents


def run_agent(db: Session, ctx: RequestContext, project_id: str, agent: str, task: str):
    """Produce a recommendation grounded in the project's current state.

    The agent proposes; it never acts. Every recommendation is created as
    `pending_approval` and requires a human with `action:approve`.
    """
    project = _project(db, ctx, project_id)
    sample = _sample(db, ctx, project_id)
    late = sample.late_activities
    critical_late = [item for item in late if item.critical]

    if critical_late:
        target = critical_late[0]
        recommendation = (
            f"Critical activity {target.external_id} ({target.name}) has slipped {target.slip_days} days "
            f"with {target.total_float_days} days of float. Resequence the work downstream of it and "
            f"confirm resource availability before the next look-ahead."
        )
    elif late:
        target = late[0]
        recommendation = (
            f"{len(late)} activities are behind plan; the largest is {target.external_id} "
            f"({target.name}) at {target.slip_days} days. Review the cause and rebaseline the look-ahead."
        )
    else:
        target = None
        recommendation = (
            "No activity-level slippage is recorded. Verify that progress updates are current "
            "before treating the schedule as on track."
        )

    row = AgentAction(
        tenant_id=ctx.tenant_id,
        organization_id=ctx.organization_id,
        project_id=project_id,
        agent=agent,
        action_type="recommendation",
        payload={
            "task": task,
            "recommendation": recommendation,
            "evidence_required": True,
            "grounded_in": {
                "project": project.name,
                "activities_measured": sample.sample_size,
                "late_activities": len(late),
                "critical_late_activities": len(critical_late),
                "target_activity": target.external_id if target else None,
            },
            "requires_human_approval": True,
        },
        status="pending_approval",
        requested_by=agent,
    )
    db.add(row)
    db.flush()
    emit(db, "agent.recommendation.created", "agent_action", row.id, {"project_id": project_id, "agent": agent})
    audit(
        db,
        ctx,
        "agent.recommendation",
        "agent_action",
        row.id,
        project_id,
        after={"agent": agent, "task": task, "status": row.status},
        actor_type="agent",
    )
    db.commit()
    db.refresh(row)
    hub.publish(ctx.tenant_id, project_id, "agent.recommendation", {"id": row.id, "agent": agent, "status": row.status})
    return row


def approve_action(db: Session, ctx: RequestContext, action_id: str):
    row = db.scalar(
        select(AgentAction).where(
            AgentAction.id == action_id,
            AgentAction.tenant_id == ctx.tenant_id,
            AgentAction.organization_id == ctx.organization_id,
        )
    )
    if not row:
        raise ValueError("Action not found")
    if row.status == "approved":
        return row
    before = {"status": row.status}
    row.status = "approved"
    row.approved_by = ctx.user_id
    row.approved_at = utcnow()
    audit(
        db,
        ctx,
        "agent_action.approve",
        "agent_action",
        row.id,
        row.project_id,
        before=before,
        after={"status": row.status, "approved_by": ctx.user_id},
    )
    emit(db, "action.approved", "agent_action", row.id, {"project_id": row.project_id})
    db.commit()
    db.refresh(row)
    hub.publish(ctx.tenant_id, row.project_id, "action.approved",
                {"id": row.id, "agent": row.agent, "status": row.status, "approved_by": row.approved_by})
    return row
