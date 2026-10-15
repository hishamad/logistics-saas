"""Daily rolling re-planning, as a dispatcher would run it.

Every morning: plan the next ``hours`` with the jobs known so far, starting from
where each truck really is. Work starting in the freeze window keeps its truck;
moving any other job away from yesterday's truck costs ``change_penalty``.
Then the day is executed exactly as planned (no disruptions yet) and the clock
moves on.

Known simplifications, to revisit with real data:
- Drivers start each morning's plan rested; driving hours are not carried
  across planning days.
- Execution follows the plan exactly; breakdowns and delays come later.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from freight.costing import calculate_cost
from freight.domain.models import Activity, Assignment, AssignmentLock, Plan, Snapshot, Window
from freight.planning.diff import PlanDiff, diff_plans
from freight.planning.engine import plan_lns

# (snapshot, seconds, seed, rounds) -> (snapshot actually planned, plan)
Planner = Callable[[Snapshot, float, int, int | None], tuple[Snapshot, Plan]]
# Called after each morning's plan: (day index, snapshot, plan, changes since yesterday).
MorningHook = Callable[[int, Snapshot, Plan, PlanDiff | None], None]


def myopic(
    snapshot: Snapshot, seconds: float, seed: int, rounds: int | None = None
) -> tuple[Snapshot, Plan]:
    return snapshot, plan_lns(snapshot, seconds=seconds, seed=seed, rounds=rounds)


@dataclass
class Fleet:
    site: dict[str, str]  # team -> where it is, or will be when free
    free_at: dict[str, datetime]  # team -> when it can take new work


@dataclass
class Week:
    executed: dict[str, Assignment] = field(default_factory=dict)
    activities: list[Activity] = field(default_factory=list)
    days: list[dict[str, object]] = field(default_factory=list)


def start_fleet(base: Snapshot) -> Fleet:
    resources = {r.id: r for r in base.resources}
    return Fleet(
        site={t.id: resources[t.tractor_id].site_id for t in base.teams},
        free_at={
            t.id: max(resources[r].availability.start for r in t.resource_ids) for t in base.teams
        },
    )


def morning(
    base: Snapshot,
    now: datetime,
    fleet: Fleet,
    week: Week,
    previous: Plan | None,
    hours: int = 48,
    freeze_hours: float = 12,
    change_penalty_minor: int = 0,
) -> Snapshot:
    """The snapshot a dispatcher would plan from at ``now``."""
    end = now + timedelta(hours=hours)
    before = {a.job_id: a for a in previous.assignments} if previous else {}
    frozen = {j for j, a in before.items() if a.pickup_at < now + timedelta(hours=freeze_hours)}
    jobs = []
    for job in base.jobs:
        if job.id in week.executed or job.state == "cancelled":
            continue
        if job.known_at and job.known_at > now and job.id not in before:
            continue
        if job.pickup_window.end <= now or job.pickup_window.start >= end:
            continue
        if job.id in frozen and job.state == "offered":
            job = job.model_copy(update={"state": "confirmed"})  # a booked offer is a commitment
        jobs.append(job)
    open_ids = {j.id for j in jobs}
    resources = []
    by_team = {r: t for t in base.teams for r in t.resource_ids}
    for r in base.resources:
        team = by_team.get(r.id)
        if team is None:
            resources.append(r)
            continue
        free = max(fleet.free_at[team.id], now)
        resources.append(
            r.model_copy(
                update={
                    "site_id": fleet.site[team.id],
                    "availability": Window(start=free, end=max(free, r.availability.end)),
                    "confirmed_at": now,
                }
            )
        )
    teams = tuple(t.model_copy(update={"home_site_id": base.home_of(t)}) for t in base.teams)
    return base.model_copy(
        update={
            "name": f"{base.name} | morning {now:%a %d %b}",
            "horizon": Window(start=now, end=end),
            "jobs": tuple(jobs),
            "resources": tuple(resources),
            "teams": teams,
            "locks": tuple(
                AssignmentLock(job_id=j, team_id=before[j].team_id)
                for j in sorted(frozen & open_ids)
            ),
            "previous": {j: a.team_id for j, a in before.items() if j in open_ids},
            "change_penalty_minor": change_penalty_minor,
            "end_values": {},
        }
    )


def execute(plan: Plan, until: datetime, fleet: Fleet, week: Week) -> None:
    """Carry out everything that starts before ``until``; a started job runs to the end."""
    by_team: dict[str, list[Activity]] = {}
    for activity in plan.activities:
        by_team.setdefault(activity.team_id, []).append(activity)
    started = {a.job_id for a in plan.assignments if a.pickup_at < until}
    for team_id, activities in by_team.items():
        activities.sort(key=lambda a: a.start)
        done = [
            a
            for a in activities
            if a.start < until or (a.job_id is not None and a.job_id in started)
        ]
        # A job started before ``until`` drags its whole sequence in; keep order intact.
        while done and done[-1].job_id is None and done[-1].start >= until:
            done.pop()
        if not done:
            continue
        week.activities.extend(done)
        fleet.site[team_id] = done[-1].to_site_id
        fleet.free_at[team_id] = done[-1].end
    for assignment in plan.assignments:
        if assignment.job_id in started:
            week.executed[assignment.job_id] = assignment


def simulate(
    base: Snapshot,
    planner: Planner = myopic,
    days: int = 7,
    hours: int = 48,
    freeze_hours: float = 12,
    change_penalty_minor: int = 0,
    seconds: float = 20,
    seed: int = 1,
    on_morning: MorningHook | None = None,
    rounds: int | None = None,
) -> dict[str, object]:
    """Run a week of mornings and score the executed result."""
    now = base.horizon.start
    fleet, week = start_fleet(base), Week()
    previous: Plan | None = None
    for _ in range(days):
        snapshot = morning(
            base, now, fleet, week, previous, hours, freeze_hours, change_penalty_minor
        )
        snapshot, plan = planner(snapshot, seconds, seed, rounds)
        done_before = len(week.executed)
        tomorrow = now + timedelta(days=1)
        communicated = {
            a.job_id for a in (previous.assignments if previous else ()) if a.pickup_at < tomorrow
        }
        changes = diff_plans(previous, plan) if previous else None
        still_open = {j.id for j in snapshot.jobs}
        nervous = (
            sum(1 for j, _, _ in changes.moved if j in communicated)
            + sum(1 for j, _ in changes.dropped if j in communicated and j in still_open)
            if changes
            else 0
        )
        week.days.append(
            {
                "morning": f"{now:%a %d %b}",
                "valid": plan.valid,
                "findings": sorted({f.code for f in plan.findings}),
                "jobs_known": len(snapshot.jobs),
                "moved": len(changes.moved) if changes else 0,
                "changed_within_a_day": nervous,
                "notified": len(
                    {t for j, a, b in changes.moved if j in communicated for t in (a, b)}
                    | {t for j, t in changes.dropped if j in communicated and j in still_open}
                )
                if changes
                else 0,
            }
        )
        if on_morning is not None:
            on_morning(len(week.days) - 1, snapshot, plan, changes)
        execute(plan, tomorrow, fleet, week)
        week.days[-1]["jobs_done"] = len(week.executed) - done_before
        previous, now = plan, tomorrow
    week_end = base.horizon.start + timedelta(days=days)
    confirmed = {
        j.id for j in base.jobs if j.state == "confirmed" and j.pickup_window.start < week_end
    }
    offered = {j.id for j in base.jobs if j.state == "offered"}
    prices = {j.id: j.revenue_minor or 0 for j in base.jobs}
    costs = calculate_cost(tuple(week.activities), base.costs)
    revenue = sum(prices[j] for j in week.executed)
    return {
        "valid_days": sum(1 for d in week.days if d["valid"]),
        "days": week.days,
        "served": len(set(week.executed) & confirmed),
        "confirmed": len(confirmed),
        "offers": len(set(week.executed) & offered),
        "revenue_sar": round(revenue / 100),
        "cost_sar": round((costs.total_minor or 0) / 100),
        "contribution_sar": round((revenue - (costs.total_minor or 0)) / 100),
        "empty_km": round(costs.empty_distance_m / 1000),
        "loaded_km": round(costs.loaded_distance_m / 1000),
        "trucks": len(base.teams),
        "moved_total": sum(int(d["moved"]) for d in week.days),  # type: ignore[call-overload]
        "changed_within_a_day": sum(int(d["changed_within_a_day"]) for d in week.days),  # type: ignore[call-overload]
    }
