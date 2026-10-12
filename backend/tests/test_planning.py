from datetime import timedelta
from decimal import Decimal

import pytest

from freight.costing import calculate_cost
from freight.domain.models import Activity, CostProfile, Rule, Window
from freight.fixtures import demo_snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.solver import solve_plan
from freight.validation import validate_plan


@pytest.fixture
def tiny():
    return demo_snapshot(job_count=3, team_count=2)


def test_both_planners_return_independently_valid_complete_plans(tiny):
    baseline = baseline_plan(tiny)
    result = solve_plan(tiny, seconds=3)
    assert baseline.valid, baseline.findings
    assert result.valid, result.findings
    assert result.coverage == baseline.coverage == "complete"
    assert result.costs.total_minor <= baseline.costs.total_minor
    assert result.costs.empty_distance_m > 0


def test_validator_detects_teleportation_and_understated_distance(tiny):
    result = solve_plan(tiny, seconds=3)
    changed = list(result.activities)
    index = next(i for i, a in enumerate(changed) if a.kind == "loaded")
    changed[index] = changed[index].model_copy(update={"distance_m": 0, "from_site_id": "depot"})
    checked = validate_plan(tiny, result.model_copy(update={"activities": tuple(changed)}))
    assert not checked.valid
    assert {"invalid_travel", "job_location"} <= {f.code for f in checked.findings}


def test_shared_trailer_is_not_extra_capacity(tiny):
    teams = (
        tiny.teams[0],
        tiny.teams[1].model_copy(update={"trailer_id": tiny.teams[0].trailer_id}),
    )
    snapshot = tiny.model_copy(update={"teams": teams})
    result = solve_plan(snapshot, seconds=3, diagnostic=True)
    assert result.valid, result.findings
    assert len({a.team_id for a in result.assignments}) <= 1


def test_unavailable_driver_cannot_be_scheduled(tiny):
    rule = Rule(
        id="maintenance",
        kind="resource_unavailable",
        resource_id="driver-01",
        window=Window(start=tiny.horizon.start, end=tiny.horizon.end + timedelta(hours=12)),
    )
    snapshot = tiny.model_copy(update={"rules": (rule,)})
    result = solve_plan(snapshot, seconds=3, diagnostic=True)
    assert result.valid, result.findings
    assert all(a.team_id != "team-01" for a in result.assignments)


def test_impossible_window_is_not_hidden(tiny):
    job = tiny.jobs[0].model_copy(
        update={
            "delivery_window": Window(
                start=tiny.horizon.start, end=tiny.horizon.start + timedelta(minutes=10)
            )
        }
    )
    snapshot = tiny.model_copy(update={"jobs": (job,)})
    strict = solve_plan(snapshot, seconds=2)
    partial = solve_plan(snapshot, seconds=2, diagnostic=True)
    assert strict.outcome == "proven_infeasible"
    assert partial.valid, partial.findings
    assert partial.coverage == "partial"
    assert partial.unserved_job_ids == (job.id,)


def test_missing_material_cost_does_not_become_zero(tiny):
    snapshot = tiny.model_copy(update={"costs": CostProfile(distance_minor_per_km=None)})
    result = baseline_plan(snapshot)
    assert result.valid
    assert result.costs.total_minor is None
    assert not result.costs.available


def test_fractional_rates_round_components_once(tiny):
    start = tiny.horizon.start
    activity = Activity(
        team_id="team-01",
        kind="empty",
        from_site_id="depot",
        to_site_id="port",
        start=start,
        end=start + timedelta(minutes=30),
        distance_m=1250,
    )
    costs = calculate_cost(
        (activity,),
        CostProfile(distance_minor_per_km=Decimal("125.5"), duty_minor_per_hour=Decimal("1000")),
    )
    assert costs.distance_minor == 157
    assert costs.duty_minor == 500
    assert costs.total_minor == 657


def test_trip_occupancy_extends_beyond_horizon(tiny):
    snapshot = tiny.model_copy(
        update={
            "horizon": Window(
                start=tiny.horizon.start, end=tiny.horizon.start + timedelta(hours=3)
            ),
            "jobs": (tiny.jobs[0],),
        }
    )
    result = solve_plan(snapshot, seconds=2)
    assert result.valid, result.findings
    assert max(a.end for a in result.activities) > snapshot.horizon.end


def test_approved_rule_changes_assignment(tiny):
    rule = Rule(
        id="prefer",
        kind="preferred_assignment",
        team_id="team-02",
        job_id=tiny.jobs[0].id,
        strength="hard",
    )
    snapshot = tiny.model_copy(update={"rules": (rule,)})
    result = solve_plan(snapshot, seconds=3)
    assert result.valid, result.findings
    assert next(a for a in result.assignments if a.job_id == tiny.jobs[0].id).team_id == "team-02"


def test_unknown_lane_is_input_error_not_infeasibility(tiny):
    result = solve_plan(tiny.model_copy(update={"lanes": tiny.lanes[1:]}))
    assert result.outcome == "model_invalid"
    assert "missing_lane" in {f.code for f in result.findings}
