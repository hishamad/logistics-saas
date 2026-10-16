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
from freight.planning.engine import Engine, Search
from freight.sheets import AVAILABILITY_TAIL
from freight.validation.validator import hours_sweep


def started_before(plan: Plan, start: datetime) -> list[str]:
    """Jobs the plan picks up before ``start``: what the dispatcher confirms as done."""
    return [
        a.job_id for a in sorted(plan.assignments, key=lambda a: a.pickup_at) if a.pickup_at < start
    ]


def roll_forward(
    operation: Snapshot,
    plan: Plan,
    start: datetime,
    days: int,
    not_done: frozenset[str] = frozenset(),
) -> tuple[Snapshot, dict[str, Any]]:
    """The operation as it stands at ``start`` if ``plan`` was carried out until then.

    ``operation`` is the current order book and fleet (it may hold orders added since
    the plan); ``plan`` is the plan being executed. ``not_done`` are jobs the plan had
    started that did not happen: they stay open, and their trucks' day leaves them
    out (the drive to their pickup too). Returns the new snapshot and a report.
    """
    if start <= operation.horizon.start:
        raise ValueError("The new start must be after the current planning window start")
    by_team: defaultdict[str, list[Activity]] = defaultdict(list)
    for activity in plan.activities:
        by_team[activity.team_id].append(activity)
    started = {a.job_id for a in plan.assignments if a.pickup_at < start} - not_done
    pickups = {j.id: j.pickup_site_id for j in operation.jobs}
    teams = {t.id for t in operation.teams}
    site: dict[str, str] = {}
    free_at: dict[str, datetime] = {}
    driver_hours: dict[str, DriverHours] = dict(operation.driver_hours)
    in_progress: list[str] = []
    for team_id, activities in by_team.items():
        if team_id not in teams:
            continue
        activities.sort(key=lambda a: a.start)
        skipped = [a for a in activities if a.job_id in not_done]
        if skipped:
            # Leave out the job and the empty drive that only served to reach it.
            gone = set(map(id, skipped))
            for leg, then in zip(activities, activities[1:], strict=False):
                if (
                    id(then) in gone
                    and leg.kind == "empty"
                    and leg.to_site_id == pickups.get(then.job_id or "")
                ):
                    gone.add(id(leg))
            activities = [a for a in activities if id(a) not in gone]
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
    references = {j.id: j.reference for j in operation.jobs}
    report = {
        "executed": len(started & {j.id for j in operation.jobs}),
        # Not done and still open; a not-done job whose pickup time passed is in "missed".
        "not_done": sorted(references.get(j, j) for j in not_done if j in kept_ids),
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


def release_impossible_locks(snapshot: Snapshot) -> tuple[Snapshot, list[str]]:
    """Frozen jobs their truck can no longer do at all (even with nothing else to do).

    Situations change after a job is frozen (a shorter window, a day off, a new rule).
    Keeping such a freeze would make the whole plan invalid, so it is released and
    reported instead. Returns the snapshot to plan and the released job ids.
    """
    if not snapshot.locks:
        return snapshot, []
    search = Search(Engine(snapshot, 1))  # every route empty
    released = [
        lock.job_id
        for lock in snapshot.locks
        if search.insertion_on(lock.job_id, lock.team_id) is None
    ]
    if not released:
        return snapshot, []
    locks = tuple(lock for lock in snapshot.locks if lock.job_id not in released)
    return snapshot.model_copy(update={"locks": locks}), released
