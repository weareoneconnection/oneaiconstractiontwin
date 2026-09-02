"""Critical path analysis over the project's own schedule logic.

The forecast used to resample observed activity variance without ever asking *where a
delay travels*. That is the gap between a statistical estimate and something a planner
recognises: a slip only matters downstream if the logic carries it there, and it is
absorbed if the successor has float.

This performs a standard CPM pass — forward for early dates, backward for late dates,
float as the difference — over the links imported with the schedule. Two properties are
deliberate:

* **It reports the network it actually has.** A schedule imported without predecessor
  columns has no logic, and the result says so instead of treating every activity as
  independent and calling that a critical path.
* **It does not overwrite the source plan.** The imported `total_float_days` and
  `critical` flags are kept as the planner stated them; the computed values sit beside
  them. When they disagree, that disagreement is the finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import RequestContext
from app.core.time import utcnow
from app.domain.models import Activity

#: Relationship types. Finish-to-start covers the overwhelming majority of construction
#: logic; the others are honoured where a source schedule uses them.
LINK_TYPES = {"FS", "SS", "FF", "SF"}


@dataclass
class Node:
    id: str
    external_id: str
    name: str
    duration: float
    predecessors: list[dict[str, Any]] = field(default_factory=list)
    successors: list[str] = field(default_factory=list)
    early_start: float = 0.0
    early_finish: float = 0.0
    late_start: float = 0.0
    late_finish: float = 0.0
    actual_slip: float = 0.0
    percent_complete: float = 0.0
    source_critical: bool = False
    source_float: float = 0.0

    #: How far this activity can slip before it delays *any successor*. Total float is
    #: shared along a path — spending it once removes it for everything downstream — so
    #: free float is the correct quantity for tracing a delay.
    free_float: float = 0.0

    @property
    def total_float(self) -> float:
        return round(self.late_start - self.early_start, 2)

    @property
    def is_critical(self) -> bool:
        return self.total_float <= 0.001


def _duration_days(activity: Activity) -> float:
    if activity.planned_start and activity.planned_finish:
        days = (activity.planned_finish - activity.planned_start).total_seconds() / 86400.0
        return max(0.0, round(days, 2))
    return 0.0


def _slip_days(activity: Activity, now: datetime) -> float:
    if not activity.planned_finish:
        return 0.0
    if activity.actual_finish:
        return max(0.0, round((activity.actual_finish - activity.planned_finish).total_seconds() / 86400.0, 2))
    if now > activity.planned_finish and float(activity.percent_complete or 0) < 100:
        return max(0.0, round((now - activity.planned_finish).total_seconds() / 86400.0, 2))
    return 0.0


def build_network(activities: Iterable[Activity], now: datetime | None = None) -> tuple[dict[str, Node], list[str]]:
    """Return (nodes by external id, warnings)."""
    moment = now or utcnow()
    nodes: dict[str, Node] = {}
    warnings: list[str] = []

    for activity in activities:
        key = (activity.external_id or activity.id).strip()
        if key in nodes:
            warnings.append(f"Duplicate activity id '{key}': only the first occurrence is used in the network.")
            continue
        nodes[key] = Node(
            id=activity.id,
            external_id=key,
            name=activity.name,
            duration=_duration_days(activity),
            predecessors=[link for link in (activity.predecessors or []) if isinstance(link, dict)],
            actual_slip=_slip_days(activity, moment),
            percent_complete=float(activity.percent_complete or 0),
            source_critical=bool(activity.critical),
            source_float=float(activity.total_float_days or 0),
        )

    for node in nodes.values():
        resolved: list[dict[str, Any]] = []
        for link in node.predecessors:
            reference = str(link.get("activity") or "").strip()
            if not reference:
                continue
            if reference not in nodes:
                warnings.append(f"{node.external_id} depends on '{reference}', which is not in this schedule.")
                continue
            resolved.append({
                "activity": reference,
                "type": str(link.get("type") or "FS").upper(),
                "lag_days": float(link.get("lag_days") or 0),
            })
            nodes[reference].successors.append(node.external_id)
        node.predecessors = resolved

    return nodes, warnings


def _topological_order(nodes: dict[str, Node]) -> tuple[list[str], list[str]]:
    """Kahn's algorithm. Any node left over sits in a cycle, which is reported."""
    indegree = {key: len(node.predecessors) for key, node in nodes.items()}
    queue = [key for key, degree in indegree.items() if degree == 0]
    order: list[str] = []
    while queue:
        key = queue.pop(0)
        order.append(key)
        for successor in nodes[key].successors:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                queue.append(successor)
    cycle = [key for key in nodes if key not in order]
    return order, cycle


def compute(activities: Iterable[Activity], now: datetime | None = None) -> tuple[dict[str, Node], list[str], list[str], dict[str, Any] | None]:
    """Run both passes once. Returns (nodes, order, warnings, blocking_reason).

    Every caller shares this result: computing the network twice once meant one caller
    read floats that had never been filled in.
    """
    nodes, warnings = build_network(activities, now)
    if not nodes:
        return nodes, [], warnings, {"available": False, "reason": "This project has no activities.", "warnings": warnings}

    linked = sum(1 for node in nodes.values() if node.predecessors)
    if linked == 0:
        return nodes, [], warnings, {
            "available": False,
            "reason": (
                "No schedule logic was imported. A critical path needs predecessor links; "
                "add a 'predecessors' column to the schedule export (for example \"A1023FS+2\")."
            ),
            "activities": len(nodes),
            "warnings": warnings,
        }

    order, cycle = _topological_order(nodes)
    if cycle:
        return nodes, [], warnings, {
            "available": False,
            "reason": f"The schedule logic contains a cycle involving {', '.join(sorted(cycle)[:6])}.",
            "activities": len(nodes),
            "warnings": warnings,
        }

    # Forward pass: the earliest each activity can start given its predecessors.
    for key in order:
        node = nodes[key]
        earliest = 0.0
        for link in node.predecessors:
            other = nodes[link["activity"]]
            lag = link["lag_days"]
            kind = link["type"] if link["type"] in LINK_TYPES else "FS"
            if kind == "FS":
                candidate = other.early_finish + lag
            elif kind == "SS":
                candidate = other.early_start + lag
            elif kind == "FF":
                candidate = other.early_finish + lag - node.duration
            else:  # SF
                candidate = other.early_start + lag - node.duration
            earliest = max(earliest, candidate)
        node.early_start = round(earliest, 2)
        node.early_finish = round(earliest + node.duration, 2)

    project_finish = max((node.early_finish for node in nodes.values()), default=0.0)

    # Backward pass: the latest each activity can finish without delaying the project.
    for node in nodes.values():
        node.late_finish = project_finish
    for key in reversed(order):
        node = nodes[key]
        if node.successors:
            latest = min(
                (
                    nodes[successor].late_start - link["lag_days"]
                    if (link := next((l for l in nodes[successor].predecessors if l["activity"] == key), None))
                    and link["type"] == "FS"
                    else nodes[successor].late_finish
                )
                for successor in node.successors
            )
            node.late_finish = round(latest, 2)
        node.late_start = round(node.late_finish - node.duration, 2)

    # Free float: the gap between when this activity finishes and when its earliest
    # successor must start. A terminal activity has none beyond its total float.
    for node in nodes.values():
        if not node.successors:
            node.free_float = node.total_float
            continue
        gaps = []
        for successor in node.successors:
            link = next(
                (item for item in nodes[successor].predecessors if item["activity"] == node.external_id),
                {"type": "FS", "lag_days": 0.0},
            )
            reference = nodes[successor].early_start if link["type"] in ("FS", "SF") else nodes[successor].early_start
            gaps.append(reference - (node.early_finish + link["lag_days"]))
        node.free_float = round(max(0.0, min(gaps)), 2)

    return nodes, order, warnings, None


def analyse(activities: Iterable[Activity], now: datetime | None = None) -> dict[str, Any]:
    """Critical path, float distribution and where the network disagrees with the plan."""
    nodes, order, warnings, blocked = compute(activities, now)
    if blocked:
        return blocked

    linked = sum(1 for node in nodes.values() if node.predecessors)
    project_finish = max((node.early_finish for node in nodes.values()), default=0.0)
    critical = [node for node in nodes.values() if node.is_critical]
    # Only activities that take part in the logic can be judged by the network. An
    # unlinked activity is an isolated node — reporting it as "the plan calls this
    # critical but the network disagrees" would be an artefact of the missing links,
    # not a finding about the schedule.
    disagreements = [
        {
            "activity": node.external_id,
            "name": node.name,
            "computed_float_days": node.total_float,
            "source_float_days": node.source_float,
            "computed_critical": node.is_critical,
            "source_critical": node.source_critical,
        }
        for node in nodes.values()
        if (node.predecessors or node.successors) and node.is_critical != node.source_critical
    ]
    unlinked = [node.external_id for node in nodes.values() if not node.predecessors and not node.successors]

    return {
        "available": True,
        "method": "cpm-forward-backward-pass",
        "activities": len(nodes),
        "activities_with_logic": linked,
        "project_duration_days": round(project_finish, 2),
        "critical_path": [
            {
                "activity": node.external_id,
                "name": node.name,
                "duration_days": node.duration,
                "early_start": node.early_start,
                "early_finish": node.early_finish,
                "total_float_days": node.total_float,
                "slip_days": node.actual_slip,
                "percent_complete": node.percent_complete,
            }
            for node in sorted(critical, key=lambda item: item.early_start)
        ],
        "float_distribution": {
            "zero": sum(1 for node in nodes.values() if node.total_float <= 0.001),
            "under_5_days": sum(1 for node in nodes.values() if 0.001 < node.total_float <= 5),
            "over_5_days": sum(1 for node in nodes.values() if node.total_float > 5),
        },
        # Where the twin's own network disagrees with the plan as imported. Neither is
        # assumed correct; the discrepancy is the finding.
        "disagreements_with_source": disagreements,
        #: Activities the network cannot say anything about, because nothing links them.
        "activities_without_logic": len(unlinked),
        "unlinked_examples": sorted(unlinked)[:10],
        "warnings": warnings,
    }


def propagate_delay(activities: Iterable[Activity], now: datetime | None = None) -> dict[str, Any]:
    """How far measured slippage actually travels through the logic.

    A slip is absorbed by a successor's float and only reaches the project finish when
    it exhausts it. This is the difference between "four activities are late" and "the
    project is four days late".
    """
    nodes, order, _warnings, blocked = compute(activities, now)
    if blocked:
        return blocked
    network = analyse(activities, now)

    # Delay leaving an activity = what arrived, plus its own slip, less the slack it has
    # before its earliest successor is affected.
    pushed: dict[str, float] = {key: 0.0 for key in nodes}
    for key in order:
        node = nodes[key]
        incoming = max((pushed[link["activity"]] for link in node.predecessors), default=0.0)
        pushed[key] = round(max(0.0, incoming + node.actual_slip - node.free_float), 2)

    terminal = [key for key, node in nodes.items() if not node.successors]
    impact = round(max((pushed[key] for key in terminal), default=0.0), 2)

    def _impact_without(excluded: str) -> float:
        """Re-run propagation with one activity's slip removed."""
        trial: dict[str, float] = {key: 0.0 for key in nodes}
        for key in order:
            node = nodes[key]
            incoming = max((trial[link["activity"]] for link in node.predecessors), default=0.0)
            slip = 0.0 if key == excluded else node.actual_slip
            trial[key] = round(max(0.0, incoming + slip - node.free_float), 2)
        return round(max((trial[key] for key in terminal), default=0.0), 2)

    # How many days of the project impact this activity is actually responsible for.
    # A boolean "reaches the finish" was misleading: an activity can pass delay to a
    # successor that absorbs it entirely.
    contributors = sorted(
        (
            {
                "activity": key,
                "name": nodes[key].name,
                "slip_days": nodes[key].actual_slip,
                "float_days": nodes[key].total_float,
                "free_float_days": nodes[key].free_float,
                "project_impact_contribution_days": round(impact - _impact_without(key), 2),
            }
            for key in nodes
            if nodes[key].actual_slip > 0
        ),
        key=lambda item: (-item["project_impact_contribution_days"], -item["slip_days"]),
    )

    return {
        **network,
        "delay_propagation": {
            "project_impact_days": impact,
            "total_measured_slip_days": round(sum(node.actual_slip for node in nodes.values()), 2),
            "absorbed_by_float_days": round(
                sum(node.actual_slip for node in nodes.values()) - impact, 2
            ),
            "contributors": contributors[:20],
            "note": (
                "Slippage is carried forward along the logic and absorbed by available float. "
                "Total measured slip is therefore normally larger than the project impact."
            ),
        },
    }
