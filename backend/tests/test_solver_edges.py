from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from itertools import permutations, product

import pytest

from freight.ai import InterpretationError, RuleInterpretation, validate_interpretation
from freight.domain.models import (
    Activity,
    Assignment,
    AssignmentLock,
    CostProfile,
    Plan,
    Rule,
    Window,
)
from freight.fixtures import demo_snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.comparison import compare_plans
from freight.planning.solver import solve_plan
from freight.validation import validate_plan


@pytest.mark.parametrize("wide_windows", [False, True])
def test_tiny_distance_optimum_matches_exhaustive_independent_oracle(wide_windows):
    snapshot = demo_snapshot(job_count=3, team_count=2)
    window = Window(start=snapshot.horizon.start, end=snapshot.horizon.end)
    snapshot = snapshot.model_copy(
        update={
            "jobs": tuple(
                j.model_copy(update={"pickup_window": window, "delivery_window": window})
                if wide_windows
                else j
                for j in snapshot.jobs
            ),
            "costs": CostProfile(
                distance_minor_per_km=Decimal("123.45"), duty_minor_per_hour=Decimal(0)
            ),
        }
    )
    matrix = {(lane.from_site_id, lane.to_site_id): lane.distance_m for lane in snapshot.lanes}
    travel = {
        (lane.from_site_id, lane.to_site_id): timedelta(minutes=lane.duration_minutes)
        for lane in snapshot.lanes
    }
    best = None
    # Enumerate every assignment and order; no planner or validator construction helpers.
    for teams in product(range(2), repeat=3):
        partitions = [
            [j for i, j in enumerate(snapshot.jobs) if teams[i] == team] for team in range(2)
        ]
        for first, second in product(permutations(partitions[0]), permutations(partitions[1])):
            distance = 0
            feasible = True
            for route in (first, second):
                at = "depot"
                clock = snapshot.horizon.start
                for job in route:
                    pickup = max(
                        clock + travel.get((at, job.pickup_site_id), timedelta()),
                        job.pickup_window.start,
                    )
                    delivered = max(
                        pickup
                        + timedelta(minutes=job.loading_minutes + job.unloading_minutes)
                        + travel.get((job.pickup_site_id, job.delivery_site_id), timedelta()),
                        job.delivery_window.start,
                    )
                    if (
                        pickup > job.pickup_window.end
                        or pickup >= snapshot.horizon.end
                        or delivered > job.delivery_window.end
                    ):
                        feasible = False
                    clock = delivered + timedelta(minutes=job.turnaround_minutes)
                    distance += matrix.get((at, job.pickup_site_id), 0) + matrix.get(
                        (job.pickup_site_id, job.delivery_site_id), 0
                    )
                    at = job.delivery_site_id
                distance += matrix.get((at, "depot"), 0)
                if clock + travel.get((at, "depot"), timedelta()) > min(
                    r.availability.end for r in snapshot.resources
                ):
                    feasible = False
            if feasible:
                best = distance if best is None else min(best, distance)
    result = solve_plan(snapshot, seconds=3)
    assert result.valid and result.outcome == "optimal", result.findings
    assert best is not None
    expected = int(
        (Decimal(best) * Decimal("123.45") / 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
    assert result.costs.total_minor == expected


def test_overlapping_calendar_blocks_are_unioned_and_idle_terminal_is_costed():
    snapshot = demo_snapshot(job_count=0, team_count=1)
    origin = snapshot.horizon.start
    busy = Window(start=origin, end=origin + timedelta(hours=2))
    rules = (
        Rule(id="driver-busy", kind="resource_unavailable", resource_id="driver-01", window=busy),
        Rule(id="truck-busy", kind="resource_unavailable", resource_id="truck-01", window=busy),
        Rule(
            id="terminal",
            kind="required_end",
            team_id="team-01",
            site_id="port",
            window=Window(start=origin, end=origin + timedelta(hours=4)),
        ),
    )
    result = solve_plan(snapshot.model_copy(update={"rules": rules}), seconds=3, diagnostic=True)
    assert result.valid and result.coverage == "complete", result.findings
    assert result.activities[0].start >= busy.end
    assert result.activities[-1].to_site_id == "port"
    assert result.costs.empty_distance_m == 28000
    assert result.costs.total_minor == 5040 + 1458


def test_exact_lock_is_honored_by_both_planners():
    snapshot = demo_snapshot(job_count=1, team_count=1)
    pickup = snapshot.jobs[0].pickup_window.start + timedelta(minutes=10)
    snapshot = snapshot.model_copy(
        update={"locks": (AssignmentLock(job_id="job-001", team_id="team-01", pickup_at=pickup),)}
    )
    for result in (baseline_plan(snapshot), solve_plan(snapshot, seconds=3)):
        assert result.valid and result.coverage == "complete", result.findings
        assert result.assignments[0].pickup_at == pickup


def test_missing_wait_time_is_detected_and_cross_input_savings_suppressed():
    snapshot = demo_snapshot(job_count=2, team_count=1)
    second = snapshot.jobs[1].model_copy(
        update={
            "pickup_window": Window(
                start=snapshot.horizon.start + timedelta(hours=10),
                end=snapshot.horizon.start + timedelta(hours=12),
            ),
            "delivery_window": Window(
                start=snapshot.horizon.start + timedelta(hours=10),
                end=snapshot.horizon.start + timedelta(hours=16),
            ),
        }
    )
    snapshot = snapshot.model_copy(
        update={
            "jobs": (snapshot.jobs[0], second),
            "locks": (
                AssignmentLock(
                    job_id="job-001",
                    team_id="team-01",
                    pickup_at=snapshot.jobs[0].pickup_window.start,
                ),
            ),
        }
    )
    baseline = baseline_plan(snapshot)
    waiting = next((a for a in baseline.activities if a.kind == "waiting"), None)
    assert waiting is not None
    checked = validate_plan(
        snapshot,
        baseline.model_copy(
            update={"activities": tuple(a for a in baseline.activities if a is not waiting)}
        ),
    )
    assert "missing_waiting" in {f.code for f in checked.findings}
    comparison = compare_plans(baseline, baseline.model_copy(update={"snapshot_hash": "other"}))
    assert not comparison["comparable"] and comparison["modeled_saving_minor"] is None


def interpretation(**overrides):
    return RuleInterpretation(
        status="proposed",
        explanation="Test interpretation",
        question=None,
        kind="preferred_assignment",
        resource_id=None,
        team_id="team-01",
        job_id="job-001",
        site_id=None,
        customer=None,
        start=None,
        end=None,
        strength="hard",
        penalty_minor=0,
        **overrides,
    )


def test_ai_unknown_entities_unsupported_and_ambiguous_output_cannot_apply():
    snapshot = demo_snapshot()
    valid = interpretation()
    with pytest.raises(InterpretationError):
        validate_interpretation(
            snapshot, "arbitrary", valid.model_copy(update={"team_id": "other-tenant-team"})
        )
    with pytest.raises(InterpretationError):
        validate_interpretation(
            snapshot, "arbitrary", valid.model_copy(update={"question": "Which team?"})
        )
    with pytest.raises(InterpretationError):
        validate_interpretation(
            snapshot, "arbitrary", valid.model_copy(update={"resource_id": "driver-01"})
        )
    result = validate_interpretation(
        snapshot, "unsupported", valid.model_copy(update={"status": "unsupported"})
    )
    assert result["rule"] is None
    approved = validate_interpretation(snapshot, "أسند الشحنة للفريق الأول", valid)
    assert approved["rule"]["team_id"] == "team-01"
    assert snapshot.rules == ()


def test_validator_rejects_interleaved_ftl_jobs_even_without_activity_overlap():
    snapshot = demo_snapshot(job_count=2, team_count=1)
    origin = snapshot.horizon.start
    jobs = tuple(
        j.model_copy(
            update={
                "pickup_site_id": "depot",
                "delivery_site_id": "depot",
                "pickup_window": snapshot.horizon,
                "delivery_window": snapshot.horizon,
                "loading_minutes": 10 if i == 0 else 5,
                "unloading_minutes": 10 if i == 0 else 5,
                "turnaround_minutes": 0,
            }
        )
        for i, j in enumerate(snapshot.jobs)
    )
    snapshot = snapshot.model_copy(update={"jobs": jobs})

    def at(minutes):
        return origin + timedelta(minutes=minutes)

    items = [
        ("loading", 0, 10, jobs[0].id),
        ("loaded", 10, 10, jobs[0].id),
        ("loading", 10, 15, jobs[1].id),
        ("loaded", 15, 15, jobs[1].id),
        ("unloading", 15, 20, jobs[1].id),
        ("turnaround", 20, 20, jobs[1].id),
        ("waiting", 20, 40, None),
        ("unloading", 40, 50, jobs[0].id),
        ("turnaround", 50, 50, jobs[0].id),
    ]
    activities = tuple(
        Activity(
            team_id="team-01",
            kind=kind,
            from_site_id="depot",
            to_site_id="depot",
            start=at(start),
            end=at(end),
            job_id=job_id,
        )
        for kind, start, end, job_id in items
    )
    assignments = (
        Assignment(
            job_id=jobs[0].id,
            team_id="team-01",
            pickup_at=at(0),
            delivery_at=at(50),
            released_at=at(50),
        ),
        Assignment(
            job_id=jobs[1].id,
            team_id="team-01",
            pickup_at=at(10),
            delivery_at=at(20),
            released_at=at(20),
        ),
    )
    plan = Plan(
        snapshot_hash=snapshot.fingerprint,
        method="manual",
        outcome="feasible",
        coverage="complete",
        activities=activities,
        assignments=assignments,
    )
    checked = validate_plan(snapshot, plan)
    assert {f.code for f in checked.findings} == {"ftl_job_overlap"}
