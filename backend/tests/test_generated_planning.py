"""Small generated schedules checked against an independent exhaustive oracle."""

from datetime import timedelta
from decimal import Decimal
from itertools import permutations

from hypothesis import given, settings
from hypothesis import strategies as st

from freight.domain.models import CostProfile, Window
from freight.fixtures import demo_snapshot
from freight.planning.solver import solve_plan


@settings(max_examples=40, deadline=None, derandomize=True)
@given(
    first_start=st.integers(0, 60),
    second_start=st.integers(0, 60),
    width=st.integers(0, 25),
    travel=st.integers(1, 15),
    loading=st.integers(0, 10),
    unloading=st.integers(0, 10),
    turnaround=st.integers(0, 8),
    completion=st.booleans(),
)
def test_generated_feasibility_and_duty_cost_match_brute_force(
    first_start, second_start, width, travel, loading, unloading, turnaround, completion
):
    snapshot = demo_snapshot(job_count=2, team_count=1)
    origin = snapshot.horizon.start
    starts = (first_start, second_start)

    def window(start, end):
        return Window(start=origin + timedelta(minutes=start), end=origin + timedelta(minutes=end))

    jobs = tuple(
        job.model_copy(
            update={
                "pickup_site_id": "depot",
                "delivery_site_id": "port",
                "pickup_window": window(start, start + width),
                "delivery_window": window(start + 12, start + width + 40),
                "delivery_window_kind": "completion" if completion else "service_start",
                "loading_minutes": loading,
                "unloading_minutes": unloading,
                "turnaround_minutes": turnaround,
            }
        )
        for job, start in zip(snapshot.jobs, starts, strict=True)
    )
    snapshot = snapshot.model_copy(
        update={
            "jobs": jobs,
            "horizon": window(0, 120),
            "resources": tuple(
                resource.model_copy(update={"availability": window(0, 150)})
                for resource in snapshot.resources
            ),
            "lanes": tuple(
                lane.model_copy(update={"duration_minutes": travel, "distance_m": 1000})
                for lane in snapshot.lanes
            ),
            "costs": CostProfile(
                distance_minor_per_km=Decimal(0), duty_minor_per_hour=Decimal(600)
            ),
        }
    )
    best = None
    # Fixed initial depot and two depot->port jobs. Enumerate route orders and
    # every legal first departure. Earliest subsequent service minimizes duty.
    for order in permutations((0, 1)):
        first = order[0]
        for departure in range(starts[first], starts[first] + width + 1):
            clock = departure
            feasible = True
            for index, job_index in enumerate(order):
                if index:
                    clock += travel  # Empty return before the second job.
                pickup = max(clock, starts[job_index])
                if pickup > starts[job_index] + width or pickup >= 120:
                    feasible = False
                    break
                service = max(
                    pickup + loading + travel,
                    starts[job_index] + 12 - (unloading if completion else 0),
                )
                delivered = service + (unloading if completion else 0)
                if delivered > starts[job_index] + width + 40:
                    feasible = False
                    break
                clock = service + unloading + turnaround
            if feasible and clock + travel <= 150:
                cost = (clock + travel - departure) * 10
                best = cost if best is None else min(best, cost)
    result = solve_plan(snapshot, seconds=1)
    if best is None:
        assert result.outcome == "proven_infeasible", result
    else:
        assert result.valid and result.outcome == "optimal", result.findings
        assert result.costs.total_minor == best


def test_new_snapshots_never_invent_missing_cost_rates():
    snapshot = demo_snapshot().model_dump()
    snapshot.pop("costs")
    from freight.domain.models import Snapshot

    parsed = Snapshot.model_validate(snapshot)
    assert not parsed.costs.complete
