"""Daily rolling re-planning: snapshots, freezing, execution and plan differences."""

from datetime import timedelta

from freight.domain.models import Assignment, Plan
from freight.fixtures import demo_snapshot
from freight.planning.daily import Week, execute, morning, simulate, start_fleet
from freight.planning.diff import diff_plans
from freight.planning.engine import plan_lns


def realistic_demo():
    return demo_snapshot(job_count=10, team_count=4).model_copy(update={"return_to_start": False})


def test_a_simulated_week_produces_valid_plans_every_morning():
    result = simulate(realistic_demo(), days=2, hours=48, seconds=1, change_penalty_minor=30_000)
    assert result["valid_days"] == 2, result["days"]
    assert result["served"] == result["confirmed"]


def test_next_morning_freezes_imminent_work_and_remembers_yesterday():
    base = realistic_demo()
    now = base.horizon.start
    fleet, week = start_fleet(base), Week()
    first = plan_lns(morning(base, now, fleet, week, None), seconds=1)
    tomorrow = now + timedelta(hours=12)
    execute(first, tomorrow, fleet, week)
    second = morning(base, tomorrow, fleet, week, first, freeze_hours=12, change_penalty_minor=1)
    frozen = {
        a.job_id
        for a in first.assignments
        if a.job_id not in week.executed and a.pickup_at < tomorrow + timedelta(hours=12)
    }
    assert {lock.job_id for lock in second.locks} == frozen
    assert all(job.id not in week.executed for job in second.jobs)
    assert second.previous and set(second.previous) <= {j.id for j in second.jobs}
    plan = plan_lns(second, seconds=1)
    assert plan.valid, plan.findings


def test_execution_moves_each_truck_to_the_end_of_its_committed_work():
    base = realistic_demo()
    now = base.horizon.start
    fleet, week = start_fleet(base), Week()
    plan = plan_lns(morning(base, now, fleet, week, None), seconds=1)
    until = now + timedelta(hours=8)
    execute(plan, until, fleet, week)
    for a in plan.assignments:
        if a.pickup_at < until:
            assert a.job_id in week.executed
            assert fleet.free_at[a.team_id] >= a.released_at


def test_plan_diff_names_moves_drops_and_retimes():
    t0 = demo_snapshot().horizon.start

    def assign(job: str, team: str, minutes: int) -> Assignment:
        at = t0 + timedelta(minutes=minutes)
        return Assignment(job_id=job, team_id=team, pickup_at=at, delivery_at=at, released_at=at)

    plan = Plan(snapshot_hash="x", method="manual", outcome="feasible", coverage="complete")
    before = plan.model_copy(
        update={"assignments": (assign("a", "t1", 0), assign("b", "t1", 60), assign("c", "t2", 0))}
    )
    after = plan.model_copy(
        update={"assignments": (assign("a", "t2", 0), assign("b", "t1", 180), assign("d", "t1", 0))}
    )
    d = diff_plans(before, after)
    assert d.moved == [("a", "t1", "t2")]
    assert d.retimed and d.retimed[0][:2] == ("b", "t1")
    assert d.added == [("d", "t1")] and d.dropped == [("c", "t2")]
    assert d.teams_to_notify == {"t1", "t2"}


def test_driving_hours_carry_into_the_next_morning():
    from freight.domain.models import DrivingRules

    base = realistic_demo().model_copy(update={"driving_rules": DrivingRules()})
    now = base.horizon.start
    fleet, week = start_fleet(base), Week()
    first = plan_lns(morning(base, now, fleet, week, None), seconds=1)
    later = now + timedelta(hours=12)
    execute(first, later, fleet, week, base.driving_rules)
    worked = {a.team_id for a in first.activities if a.start < later and a.kind != "rest"}
    assert worked and worked <= set(fleet.hours)
    second = morning(base, later, fleet, week, first)
    assert second.driver_hours == fleet.hours
    assert plan_lns(second, seconds=1).valid
