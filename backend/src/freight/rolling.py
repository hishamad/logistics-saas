"""Roll the operation forward to the next planning day, from the last plan.

Until real tracking data exists, work planned to start before the new start is
assumed done as planned: those orders leave the order book, a job already under
way runs to its end, each truck is where the plan left it, and each driver
carries the driving hours the plan gave them. Anything that cannot be carried
silently (contract orders whose pickup time passed without a truck) is reported.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from freight.domain.models import Activity, DriverHours, Plan, Snapshot, Window
from freight.validation.validator import hours_sweep

AVAILABILITY_TAIL = timedelta(days=2)


def roll_forward(
    operation: Snapshot, plan: Plan, start: datetime, days: int
) -> tuple[Snapshot, dict[str, Any]]:
    """The operation as it stands at ``start`` if ``plan`` was carried out until then.

    ``operation`` is the current order book and fleet (it may hold orders added since
    the plan); ``plan`` is the plan being executed. Returns the new snapshot and a report.
    """
    if start <= operation.horizon.start:
        raise ValueError("The new start must be after the current planning window start")
    by_team: defaultdict[str, list[Activity]] = defaultdict(list)
    for activity in plan.activities:
        by_team[activity.team_id].append(activity)
    started = {a.job_id for a in plan.assignments if a.pickup_at < start}
    teams = {t.id for t in operation.teams}
    site: dict[str, str] = {}
    free_at: dict[str, datetime] = {}
    driver_hours: dict[str, DriverHours] = dict(operation.driver_hours)
    in_progress: list[str] = []
    for team_id, activities in by_team.items():
        if team_id not in teams:
            continue
        activities.sort(key=lambda a: a.start)
        done = [a for a in activities if a.start < start or (a.job_id in started)]
        while done and done[-1].job_id is None and done[-1].start >= start:
            done.pop()
        # Waiting or resting into the new day is not work; the truck is free at ``start``.
        while done and done[-1].kind in ("waiting", "rest") and done[-1].end > start:
            done.pop()
        if not done:
            continue
        site[team_id] = done[-1].to_site_id
        free_at[team_id] = done[-1].end
        if done[-1].end > start and done[-1].job_id:
            in_progress.append(done[-1].job_id)
        if operation.driving_rules is not None:
            after = hours_sweep(operation.driving_rules, done, driver_hours.get(team_id))[1]
            if after is not None:
                driver_hours[team_id] = after

    end = start + timedelta(days=days)
    kept, missed = [], []
    for job in operation.jobs:
        if job.id in started or job.state == "cancelled":
            continue
        if job.pickup_window.end <= start:
            if job.state == "confirmed":
                missed.append(job)  # its pickup time passed without a truck
            continue
        kept.append(job)
    kept_ids = {j.id for j in kept}

    team_of = {r: t.id for t in operation.teams for r in t.resource_ids}
    resources = []
    for r in operation.resources:
        owner = team_of.get(r.id)
        current = site.get(owner, r.site_id) if owner else r.site_id
        free = max(free_at.get(owner, start) if owner else start, start, r.availability.start)
        resources.append(
            r.model_copy(
                update={
                    "site_id": current,
                    "availability": Window(start=free, end=max(free, end + AVAILABILITY_TAIL)),
                    "confirmed_at": start,
                    "unavailable": tuple(w for w in r.unavailable if w.end > start),
                }
            )
        )
    homes = {t.id: operation.home_of(t) for t in operation.teams}
    new_teams = tuple(t.model_copy(update={"home_site_id": homes[t.id]}) for t in operation.teams)
    previous = {
        a.job_id: a.team_id for a in plan.assignments if a.job_id in kept_ids and a.team_id in teams
    }
    data = dict(operation) | {
        "horizon": Window(start=start, end=end),
        "jobs": tuple(kept),
        "resources": tuple(resources),
        "teams": new_teams,
        "locks": tuple(lock for lock in operation.locks if lock.job_id in kept_ids),
        "rules": tuple(
            rule
            for rule in operation.rules
            if (rule.job_id is None or rule.job_id in kept_ids)
            and (rule.window is None or rule.window.end > start)
        ),
        "previous": previous,
        "driver_hours": {t: h for t, h in driver_hours.items() if t in teams}
        if operation.driving_rules
        else {},
    }
    rolled = Snapshot.model_validate(data)
    report = {
        "executed": len(started & {j.id for j in operation.jobs}),
        "in_progress": sorted(in_progress),
        "missed": [{"job": j.id, "ref": j.reference, "customer": j.customer} for j in missed],
        "kept": len(kept),
        "trucks_moved": sum(
            1 for t in operation.teams if site.get(t.id, homes[t.id]) != homes[t.id]
        ),
        "drivers_with_hours": len(rolled.driver_hours),
        "locks_dropped": len(operation.locks) - len(rolled.locks),
        "rules_dropped": len(operation.rules) - len(rolled.rules),
    }
    return rolled, report


def planning_view(operation: Snapshot) -> tuple[Snapshot, int]:
    """What one plan sees: orders whose pickup starts after the window wait for a later plan.

    The order book may run past the planning window; those orders are not unserved,
    just not yet due. Returns the snapshot to plan and how many orders wait.
    """
    end = operation.horizon.end
    due = tuple(j for j in operation.jobs if j.pickup_window.start < end)
    if len(due) == len(operation.jobs):
        return operation, 0
    ids = {j.id for j in due}
    data = dict(operation) | {
        "jobs": due,
        "locks": tuple(lock for lock in operation.locks if lock.job_id in ids),
        "rules": tuple(r for r in operation.rules if r.job_id is None or r.job_id in ids),
        "previous": {j: t for j, t in operation.previous.items() if j in ids},
    }
    return Snapshot.model_validate(data), len(operation.jobs) - len(due)
