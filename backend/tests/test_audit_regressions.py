"""Engine regression cases found during the first build's audit."""

from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from freight.domain.models import CostProfile, Lane, Rule, Snapshot, Window
from freight.domain.time import overlaps
from freight.fixtures import demo_snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.solver import solve_plan


def test_empty_intervals_do_not_overlap_but_positive_intervals_do():
    origin = demo_snapshot().horizon.start
    end = origin + timedelta(hours=2)
    point = origin + timedelta(hours=1)
    assert not overlaps(point, point, origin, end)
    assert not overlaps(origin, end, point, point)
    assert overlaps(origin, end, point, end)


def test_impossible_lane_and_unknown_manual_customer_are_rejected():
    with pytest.raises(ValidationError):
        Lane(from_site_id="a", to_site_id="b", distance_m=500, duration_minutes=0)
    with pytest.raises(ValidationError):
        Lane(from_site_id="a", to_site_id="a", distance_m=500, duration_minutes=5)
    snapshot = demo_snapshot()
    rule = Rule(
        id="bad-customer", kind="customer_eligibility", team_id="team-01", customer="unknown"
    )
    with pytest.raises(ValidationError):
        Snapshot.model_validate(snapshot.model_dump() | {"rules": [rule]})


def test_baseline_reschedules_idle_terminal_move_around_busy_window():
    snapshot = demo_snapshot(job_count=0, team_count=1)
    origin = snapshot.horizon.start
    busy = Window(start=origin, end=origin + timedelta(hours=2))
    snapshot = snapshot.model_copy(
        update={
            "rules": (
                Rule(id="busy", kind="resource_unavailable", resource_id="driver-01", window=busy),
                Rule(
                    id="return",
                    kind="required_end",
                    team_id="team-01",
                    site_id="port",
                    window=Window(start=origin, end=origin + timedelta(hours=4)),
                ),
            )
        }
    )
    plan = baseline_plan(snapshot)
    assert plan.valid and plan.coverage == "complete", plan.findings
    assert plan.activities[0].start >= busy.end


def test_large_allowed_costs_do_not_overflow_dense_objective():
    snapshot = demo_snapshot(job_count=12, team_count=8)
    snapshot = snapshot.model_copy(
        update={
            "costs": CostProfile(
                distance_minor_per_km=Decimal("99999.99"), duty_minor_per_hour=Decimal("99999.99")
            ),
            "lanes": tuple(
                lane.model_copy(update={"distance_m": 10_000_000}) for lane in snapshot.lanes
            ),
        }
    )
    baseline = baseline_plan(snapshot)
    result = solve_plan(snapshot, seconds=3, hint=baseline)
    assert result.outcome != "model_invalid", result.findings
    assert result.valid, result.findings
