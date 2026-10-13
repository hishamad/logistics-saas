"""The min-cost-flow bound never exceeds what a real plan can achieve."""

import pytest

from freight.fixtures import demo_snapshot
from freight.planning.bounds import lower_bound
from freight.planning.engine import plan_lns
from freight.planning.solver import solve_plan


@pytest.mark.parametrize(("jobs", "teams"), [(4, 2), (8, 4), (10, 3)])
def test_bound_never_exceeds_the_proven_optimum(jobs, teams):
    snapshot = demo_snapshot(job_count=jobs, team_count=teams)
    proven = solve_plan(snapshot, seconds=30, diagnostic=True)
    assert proven.outcome == "optimal" and proven.costs and proven.costs.total_minor is not None
    served = {a.job_id for a in proven.assignments}
    snapshot = snapshot.model_copy(
        update={"jobs": tuple(j for j in snapshot.jobs if j.id in served)}
    )
    proven = solve_plan(snapshot, seconds=30)
    bound = lower_bound(snapshot, served)
    assert bound is not None and proven.costs and proven.costs.total_minor is not None
    assert bound <= proven.costs.total_minor


def test_bound_never_exceeds_an_engine_plan_with_driving_rules():
    from freight.domain.models import DrivingRules

    snapshot = demo_snapshot(job_count=12, team_count=4).model_copy(
        update={"driving_rules": DrivingRules(), "return_to_start": False}
    )
    plan = plan_lns(snapshot, seconds=1)
    assert plan.valid and plan.costs and plan.costs.total_minor is not None, plan.findings
    bound = lower_bound(snapshot, {a.job_id for a in plan.assignments})
    assert bound is not None and bound <= plan.costs.total_minor


def test_unreachable_work_makes_the_relaxation_infeasible():
    snapshot = demo_snapshot(job_count=3, team_count=1)
    job = snapshot.jobs[0]
    late = job.model_copy(update={"equipment": "flatbed"})  # no flatbed trailer exists here
    snapshot = snapshot.model_copy(update={"jobs": (late, *snapshot.jobs[1:])})
    assert lower_bound(snapshot, {late.id}) is None
