"""The ruin-and-recreate engine, checked by the independent validator."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from freight.domain.models import (
    Activity,
    CostProfile,
    DrivingRules,
    Job,
    Lane,
    Resource,
    Site,
    Snapshot,
    Team,
    Window,
)
from freight.fixtures import demo_snapshot
from freight.planning.engine import plan_lns
from freight.planning.solver import solve_plan
from freight.validation.validator import driving_findings

ORIGIN = datetime(2026, 10, 18, 3, tzinfo=UTC)


def hours(value: float) -> datetime:
    return ORIGIN + timedelta(hours=value)


def two_site_snapshot(
    jobs: list[Job],
    *,
    drive_minutes: int = 120,
    unavailable: tuple[Window, ...] = (),
    **policy: object,
) -> Snapshot:
    available = Window(start=ORIGIN, end=hours(24 * 6))
    resources = [
        Resource(
            id="truck",
            name="Truck",
            kind="tractor",
            site_id="a",
            availability=available,
            confirmed_at=ORIGIN,
        ),
        Resource(
            id="trailer",
            name="Trailer",
            kind="trailer",
            site_id="a",
            availability=available,
            confirmed_at=ORIGIN,
            equipment="dry_van",
            capacity_kg=25_000,
        ),
        Resource(
            id="driver",
            name="Driver",
            kind="driver",
            site_id="a",
            availability=available,
            unavailable=unavailable,
            confirmed_at=ORIGIN,
        ),
    ]
    lanes = [
        Lane(
            from_site_id=x,
            to_site_id=y,
            distance_m=drive_minutes * 1000,
            duration_minutes=drive_minutes,
        )
        for x, y in (("a", "b"), ("b", "a"))
    ]
    return Snapshot(
        tenant_id="test",
        scope_id="engine",
        name="Two sites",
        horizon=Window(start=ORIGIN, end=hours(24 * 4)),
        sites=(Site(id="a", name="A"), Site(id="b", name="B")),
        resources=tuple(resources),
        teams=(
            Team(
                id="team", name="Team", tractor_id="truck", trailer_id="trailer", driver_id="driver"
            ),
        ),
        jobs=tuple(jobs),
        lanes=tuple(lanes),
        costs=CostProfile(
            distance_minor_per_km=Decimal("100"), duty_minor_per_hour=Decimal("3000")
        ),
        **policy,  # type: ignore[arg-type]
    )


def job(
    job_id: str,
    pickup: str,
    delivery: str,
    pickup_hours: tuple[float, float],
    delivery_hours: tuple[float, float],
    *,
    state: str = "confirmed",
    revenue: int = 100_000,
) -> Job:
    return Job(
        id=job_id,
        reference=job_id.upper(),
        customer="Customer",
        pickup_site_id=pickup,
        delivery_site_id=delivery,
        pickup_window=Window(start=hours(pickup_hours[0]), end=hours(pickup_hours[1])),
        delivery_window=Window(start=hours(delivery_hours[0]), end=hours(delivery_hours[1])),
        equipment="dry_van",
        weight_kg=10_000,
        state=state,  # type: ignore[arg-type]
        revenue_minor=revenue,
    )


def test_engine_matches_the_proven_optimum_on_the_demo():
    snapshot = demo_snapshot()
    proven = solve_plan(snapshot, seconds=20)
    plan = plan_lns(snapshot, seconds=2)
    assert proven.outcome == "optimal" and proven.costs and proven.costs.total_minor
    assert plan.valid and plan.coverage == "complete", plan.findings
    assert plan.costs and plan.costs.total_minor is not None
    assert plan.costs.total_minor <= proven.costs.total_minor


def test_long_trip_takes_breaks_and_an_overnight_rest():
    # 20 hours of driving needs two breaks per day and two daily rests under default rules.
    snapshot = two_site_snapshot(
        [job("long", "a", "b", (1, 3), (1, 72))],
        drive_minutes=1200,
        driving_rules=DrivingRules(),
        return_to_start=False,
    )
    plan = plan_lns(snapshot, seconds=1)
    assert plan.valid, plan.findings
    loaded = next(a for a in plan.activities if a.kind == "loaded")
    kinds = [p.kind for p in loaded.pauses]
    assert kinds.count("rest") == 2 and "break" in kinds
    assert loaded.end - loaded.start == timedelta(minutes=DrivingRules().elapsed(1200))


def test_validator_flags_driving_without_breaks():
    nonstop = Activity(
        team_id="team",
        kind="loaded",
        from_site_id="a",
        to_site_id="b",
        start=ORIGIN,
        end=hours(10),
        job_id="long",
        distance_m=1,
    )
    codes = {code for code, _ in driving_findings(DrivingRules(), [nonstop])}
    assert {"continuous_driving", "daily_driving"} <= codes


def test_day_off_is_spent_at_home_between_jobs():
    day_off = Window(start=hours(20), end=hours(44))
    snapshot = two_site_snapshot(
        [job("before", "a", "b", (1, 4), (1, 12)), job("after", "a", "b", (46, 50), (46, 60))],
        unavailable=(day_off,),
        rest_at_home=True,
        return_to_start=False,
        driving_rules=DrivingRules(),
    )
    plan = plan_lns(snapshot, seconds=1)
    assert plan.valid and plan.coverage == "complete", plan.findings
    resting = next(a for a in plan.activities if a.start <= day_off.start < a.end)
    assert resting.kind == "rest" and resting.from_site_id == "a"


def test_offers_are_taken_only_when_they_earn_more_than_they_cost():
    confirmed = job("contract", "a", "b", (1, 3), (1, 12))
    paying = job("backhaul", "b", "a", (4, 12), (4, 24), state="offered", revenue=200_000)
    cheap = job("loss", "b", "a", (30, 36), (30, 48), state="offered", revenue=100)
    snapshot = two_site_snapshot([confirmed, paying, cheap], return_to_start=False)
    plan = plan_lns(snapshot, seconds=1)
    assert plan.valid, plan.findings
    served = {a.job_id for a in plan.assignments}
    assert served == {"contract", "backhaul"}
    assert plan.costs and plan.costs.revenue_minor == 300_000


def test_a_lucrative_offer_never_displaces_confirmed_work():
    confirmed = job("contract", "a", "b", (1, 2), (1, 6))
    clash = job("offer", "a", "b", (1, 2), (1, 6), state="offered", revenue=10_000_000)
    snapshot = two_site_snapshot([confirmed, clash], return_to_start=False)
    plan = plan_lns(snapshot, seconds=1)
    assert plan.valid and plan.coverage == "complete", plan.findings
    assert {a.job_id for a in plan.assignments} == {"contract"}


def test_validator_rejects_a_day_off_spent_away_from_home():
    from freight.validation import validate_plan

    day_off = Window(start=hours(20), end=hours(44))
    rule = {"rest_at_home": True, "return_to_start": False}
    snapshot = two_site_snapshot(
        [job("out", "a", "b", (1, 4), (1, 12))], unavailable=(day_off,), **rule
    )
    plan = plan_lns(snapshot, seconds=1)
    assert plan.valid, plan.findings
    # Drop the drive home: the truck now sits at B through the day off.
    stranded = plan.model_copy(
        update={
            "activities": tuple(
                a for a in plan.activities if a.job_id or a.kind != "empty" or a.to_site_id != "a"
            )
        }
    )
    codes = {f.code for f in validate_plan(snapshot, stranded).findings}
    assert "rest_away_from_home" in codes


def test_truck_leaves_later_instead_of_waiting_on_paid_time():
    # Pickup is open 1-10 h, the drive is 2 h, but delivery only opens at 12 h:
    # the cheapest plan loads late, not early followed by a long paid wait.
    snapshot = two_site_snapshot([job("late", "a", "b", (1, 10), (12, 20))], return_to_start=False)
    plan = plan_lns(snapshot, seconds=1)
    assert plan.valid, plan.findings
    assert not [a for a in plan.activities if a.kind == "waiting"]
    assignment = plan.assignments[0]
    loading = next(a for a in plan.activities if a.kind == "loading")
    assert assignment.pickup_at == loading.start >= hours(9)


def test_a_day_off_already_running_at_plan_start_is_waited_out_at_home():
    # Daily re-planning starts mid-day-off: the driver is home until 6 h, then works.
    day_off = Window(start=hours(-10), end=hours(6))
    snapshot = two_site_snapshot(
        [job("after-rest", "a", "b", (7, 10), (7, 20))],
        unavailable=(day_off,),
        rest_at_home=True,
        return_to_start=False,
        driving_rules=DrivingRules(),
    )
    plan = plan_lns(snapshot, seconds=1)
    assert plan.valid and plan.coverage == "complete", plan.findings
    assert plan.assignments[0].pickup_at >= day_off.end
