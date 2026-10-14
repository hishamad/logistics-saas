"""What changed between two plans, in the terms a dispatcher acts on."""

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from freight.domain.models import Plan

RIYADH = ZoneInfo("Asia/Riyadh")


@dataclass
class PlanDiff:
    moved: list[tuple[str, str, str]] = field(default_factory=list)  # job, from team, to team
    added: list[tuple[str, str]] = field(default_factory=list)  # job, team
    dropped: list[tuple[str, str]] = field(default_factory=list)  # job, team it had
    retimed: list[tuple[str, str, datetime, datetime]] = field(default_factory=list)
    unchanged: int = 0

    @property
    def teams_to_notify(self) -> set[str]:
        """Teams whose instructions change: they gain, lose or re-time work."""
        teams = {t for _, a, b in self.moved for t in (a, b)}
        teams |= {t for _, t in self.added} | {t for _, t in self.dropped}
        teams |= {t for _, t, _, _ in self.retimed}
        return teams

    @property
    def changes(self) -> int:
        return len(self.moved) + len(self.dropped) + len(self.retimed)


def diff_plans(before: Plan, after: Plan, retime_minutes: int = 30) -> PlanDiff:
    """Compare assignments. Jobs only in ``after`` are added; only in ``before`` dropped."""
    old = {a.job_id: a for a in before.assignments}
    new = {a.job_id: a for a in after.assignments}
    result = PlanDiff()
    for job_id, a in new.items():
        previous = old.get(job_id)
        if previous is None:
            result.added.append((job_id, a.team_id))
        elif previous.team_id != a.team_id:
            result.moved.append((job_id, previous.team_id, a.team_id))
        elif abs((a.pickup_at - previous.pickup_at).total_seconds()) > retime_minutes * 60:
            result.retimed.append((job_id, a.team_id, previous.pickup_at, a.pickup_at))
        else:
            result.unchanged += 1
    result.dropped = [(j, a.team_id) for j, a in old.items() if j not in new]
    return result


def describe(diff: PlanDiff, references: dict[str, str] | None = None) -> str:
    ref = references or {}

    def name(job_id: str) -> str:
        return ref.get(job_id, job_id)

    lines = [
        f"Unchanged {diff.unchanged} | moved {len(diff.moved)} | new {len(diff.added)} | "
        f"dropped {len(diff.dropped)} | re-timed {len(diff.retimed)} | "
        f"teams to notify {len(diff.teams_to_notify)}"
    ]
    lines += [f"  moved    {name(j)}: {a} -> {b}" for j, a, b in diff.moved]
    lines += [f"  dropped  {name(j)} (was {t})" for j, t in diff.dropped]
    lines += [
        f"  re-timed {name(j)} on {t}: pickup "
        f"{x.astimezone(RIYADH):%a %H:%M} -> {y.astimezone(RIYADH):%a %H:%M} Riyadh"
        for j, t, x, y in diff.retimed
    ]
    return "\n".join(lines)
