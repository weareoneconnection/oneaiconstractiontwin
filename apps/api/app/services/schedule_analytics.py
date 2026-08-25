"""Schedule analytics derived from the project's own activity records.

The risk and forecast engines used to run on constants: a fixed intercept, a fixed
sigma and a `random.gauss` draw that never touched the schedule. Everything here is
computed from Activity rows, and every result reports the sample it was built from
so a thin project cannot silently produce a confident-looking number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.domain.models import Activity


@dataclass
class ActivityVariance:
    activity_id: str
    external_id: str
    name: str
    slip_days: float
    critical: bool
    total_float_days: float
    percent_complete: float
    state: str


@dataclass
class ScheduleSample:
    """Observed slippage of a project, with everything needed to judge its weight."""

    variances: list[ActivityVariance] = field(default_factory=list)
    total_activities: int = 0

    @property
    def slips(self) -> list[float]:
        return [item.slip_days for item in self.variances]

    @property
    def critical_slips(self) -> list[float]:
        return [item.slip_days for item in self.variances if item.critical]

    @property
    def sample_size(self) -> int:
        return len(self.variances)

    @property
    def mean_slip(self) -> float:
        return sum(self.slips) / len(self.slips) if self.slips else 0.0

    @property
    def critical_mean_slip(self) -> float:
        values = self.critical_slips
        return sum(values) / len(values) if values else 0.0

    @property
    def stdev_slip(self) -> float:
        if len(self.slips) < 2:
            return 0.0
        mean = self.mean_slip
        return (sum((value - mean) ** 2 for value in self.slips) / (len(self.slips) - 1)) ** 0.5

    @property
    def late_activities(self) -> list[ActivityVariance]:
        return sorted(
            [item for item in self.variances if item.slip_days > 0],
            key=lambda item: (-item.slip_days, item.total_float_days),
        )

    @property
    def data_quality(self) -> str:
        if self.sample_size >= 30:
            return "sufficient"
        if self.sample_size >= 8:
            return "thin"
        return "insufficient"


def _days(later: datetime, earlier: datetime) -> float:
    return round((later - earlier).total_seconds() / 86400.0, 2)


def collect_schedule_sample(
    db: Session, tenant_id: str, organization_id: str, project_id: str, at: datetime | None = None
) -> ScheduleSample:
    """Measure per-activity slippage: finish variance for completed work, elapsed
    overrun for work that is late and still open."""
    now = at or utcnow()
    rows = list(
        db.scalars(
            select(Activity).where(
                Activity.project_id == project_id,
                Activity.tenant_id == tenant_id,
                Activity.organization_id == organization_id,
            )
        ).all()
    )
    sample = ScheduleSample(total_activities=len(rows))
    for row in rows:
        planned_finish = row.planned_finish
        if not planned_finish:
            continue
        if row.actual_finish:
            slip = _days(row.actual_finish, planned_finish)
            state = "completed"
        elif now > planned_finish:
            slip = _days(now, planned_finish)
            state = "overrunning"
        elif row.actual_start and row.planned_start and row.actual_start > row.planned_start:
            slip = _days(row.actual_start, row.planned_start)
            state = "started_late"
        else:
            slip = 0.0
            state = "on_track"
        sample.variances.append(
            ActivityVariance(
                activity_id=row.id,
                external_id=row.external_id,
                name=row.name,
                slip_days=slip,
                critical=bool(row.critical),
                total_float_days=float(row.total_float_days or 0.0),
                percent_complete=float(row.percent_complete or 0.0),
                state=state,
            )
        )
    return sample
