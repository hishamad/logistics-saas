"""Look-ahead: value curves from the network model, and how the engine uses them."""

from collections import Counter

from test_engine import job, two_site_snapshot

from freight.fixtures import demo_snapshot
from freight.planning.engine import plan_lns
from freight.planning.lookahead import (
    ValueModel,
    forecast_from_jobs,
    plan_with_lookahead,
)


def test_forecast_turns_jobs_into_daily_lane_rates():
    snapshot = demo_snapshot()  # 8 jobs over 2 days on 4 lanes
    forecast = forecast_from_jobs(snapshot)
    assert sum(f.loads_per_day for f in forecast) == len(snapshot.jobs) / 2


def test_value_curves_fall_as_a_site_fills_up():
    snapshot = demo_snapshot()
    model = ValueModel(snapshot, forecast_from_jobs(snapshot), hours=48, bucket_hours=6)
    empty = model.value_curves(Counter(), extra=6)
    crowded = model.value_curves(Counter({"port": 20}), extra=6)
    for curve in empty.values():
        assert all(a >= b >= 0 for a, b in zip(curve, curve[1:], strict=False))
    assert empty["port"][0] > 0
    assert crowded["port"][-1] <= empty["port"][0]


def test_an_offer_that_strands_the_truck_is_declined_when_positions_have_value():
    confirmed = job("contract", "a", "b", (1, 3), (1, 12))
    back = job("backhaul", "b", "a", (4, 12), (4, 24), state="offered", revenue=200_000)
    plain = two_site_snapshot([confirmed, back], return_to_start=False)
    assert "backhaul" in {a.job_id for a in plan_lns(plain, seconds=1).assignments}
    # Ending at B is worth far more than A: carrying the backhaul to A gives that up.
    valued = plain.model_copy(update={"end_values": {"a": (0,), "b": (500_000,)}})
    plan = plan_lns(valued, seconds=1)
    assert plan.valid, plan.findings
    assert {a.job_id for a in plan.assignments} == {"contract"}


def test_plan_with_lookahead_returns_a_valid_plan_for_its_snapshot():
    snapshot = demo_snapshot(job_count=8, team_count=4).model_copy(
        update={"return_to_start": False}
    )
    valued, plan = plan_with_lookahead(snapshot, seconds=3)
    assert valued.end_values and plan.snapshot_hash == valued.fingerprint
    assert plan.valid and plan.coverage == "complete", plan.findings
