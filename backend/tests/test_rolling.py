from datetime import timedelta

import pytest

from freight.domain.models import DrivingRules
from freight.fixtures import demo_snapshot
from freight.planning.engine import plan_lns, routes_of
from freight.rolling import roll_forward


def operation():
    base = demo_snapshot(job_count=10, team_count=4)
    return base.model_copy(update={"return_to_start": False, "driving_rules": DrivingRules()})


def test_rolling_day_after_day_keeps_plans_valid_and_carries_hours():
    snapshot = operation()
    plan = plan_lns(snapshot, rounds=200, seed=1)
    jobs_before = {j.id for j in snapshot.jobs}
    for day in range(1, 3):
        start = snapshot.horizon.start + timedelta(hours=12)
        snapshot, report = roll_forward(snapshot, plan, start, 2)
        started = {a.job_id for a in plan.assignments if a.pickup_at < start}
        assert started.isdisjoint(j.id for j in snapshot.jobs)
        assert report["executed"] == len(started)
        worked = {a.team_id for a in plan.activities if a.start < start}
        assert worked <= set(snapshot.driver_hours), day
        plan = plan_lns(snapshot, rounds=200, seed=1, initial=routes_of(plan))
        assert plan.valid, (day, plan.findings)
    assert {j.id for j in snapshot.jobs} < jobs_before


def test_trucks_continue_from_where_the_plan_left_them():
    snapshot = operation()
    plan = plan_lns(snapshot, rounds=200, seed=1)
    start = snapshot.horizon.start + timedelta(hours=12)
    rolled, _ = roll_forward(snapshot, plan, start, 2)
    resources = {r.id: r for r in rolled.resources}
    started = {a.job_id for a in plan.assignments if a.pickup_at < start}
    for team in rolled.teams:
        # Anything begun before the cut-off (or part of a started job) is carried out,
        # so the truck ends at the last such activity's destination.
        begun = sorted(
            (
                a
                for a in plan.activities
                if a.team_id == team.id
                and (a.start < start or a.job_id in started)
                and not (a.kind in ("waiting", "rest") and a.end > start)
            ),
            key=lambda a: a.start,
        )
        if begun:
            assert resources[team.tractor_id].site_id == begun[-1].to_site_id
        assert resources[team.tractor_id].availability.start >= start


def test_contract_orders_whose_pickup_passed_unplanned_are_reported():
    snapshot = operation()
    plan = plan_lns(snapshot, rounds=200, seed=1)
    victim = min(plan.assignments, key=lambda a: a.pickup_at)
    unplanned = plan.model_copy(
        update={
            "assignments": tuple(a for a in plan.assignments if a.job_id != victim.job_id),
            "activities": tuple(a for a in plan.activities if a.job_id != victim.job_id),
        }
    )
    job = next(j for j in snapshot.jobs if j.id == victim.job_id)
    start = job.pickup_window.end + timedelta(minutes=1)
    rolled, report = roll_forward(snapshot, unplanned, start, 2)
    assert victim.job_id in {m["job"] for m in report["missed"]}
    assert victim.job_id not in {j.id for j in rolled.jobs}


def test_rolling_backwards_is_refused():
    snapshot = operation()
    plan = plan_lns(snapshot, rounds=50, seed=1)
    with pytest.raises(ValueError):
        roll_forward(snapshot, plan, snapshot.horizon.start, 2)
