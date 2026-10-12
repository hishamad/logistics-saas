"""Clearly synthetic examples. Lane values are not Saudi road estimates."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from freight.domain.models import CostProfile, Job, Lane, Resource, Site, Snapshot, Team, Window


def demo_snapshot(
    *, tenant_id: str = "demo", scope_id: str = "dammam", job_count: int = 8, team_count: int = 4
) -> Snapshot:
    origin = datetime(2026, 10, 12, 3, tzinfo=UTC)  # 06:00 Riyadh
    horizon = Window(start=origin, end=origin + timedelta(hours=48))
    sites = (
        Site(id="depot", name="Dammam · Demo depot", name_ar="الدمام · مستودع تجريبي"),
        Site(id="port", name="Port warehouse · Demo", name_ar="مستودع الميناء · تجريبي"),
        Site(id="industrial", name="Industrial park · Demo", name_ar="المدينة الصناعية · تجريبي"),
        Site(id="inland", name="Inland hub · Demo", name_ar="المركز الداخلي · تجريبي"),
    )
    # Symmetric, explicitly synthetic travel assumptions for repeatable fixtures.
    matrix = ((0, 35, 65, 150), (35, 0, 50, 135), (65, 50, 0, 110), (150, 135, 110, 0))
    lanes = tuple(
        Lane(
            from_site_id=a.id,
            to_site_id=b.id,
            duration_minutes=matrix[i][j],
            distance_m=matrix[i][j] * 800,
            source="Synthetic fixture — not a road estimate",
        )
        for i, a in enumerate(sites)
        for j, b in enumerate(sites)
        if i != j
    )
    resources: list[Resource] = []
    teams: list[Team] = []
    for i in range(team_count):
        number = f"{i + 1:02}"
        available = Window(start=origin, end=origin + timedelta(hours=60))
        resources.extend(
            [
                Resource(
                    id=f"truck-{number}",
                    name=f"Truck {number}",
                    kind="tractor",
                    site_id="depot",
                    availability=available,
                    confirmed_at=origin,
                ),
                Resource(
                    id=f"trailer-{number}",
                    name=f"Trailer {number}",
                    kind="trailer",
                    site_id="depot",
                    availability=available,
                    confirmed_at=origin,
                    equipment="flatbed" if i % 3 == 2 else "dry_van",
                    capacity_kg=28000,
                ),
                Resource(
                    id=f"driver-{number}",
                    name=f"Demo driver {number}",
                    kind="driver",
                    site_id="depot",
                    availability=available,
                    confirmed_at=origin,
                ),
            ]
        )
        teams.append(
            Team(
                id=f"team-{number}",
                name=f"Team {number}",
                tractor_id=f"truck-{number}",
                trailer_id=f"trailer-{number}",
                driver_id=f"driver-{number}",
            )
        )
    jobs: list[Job] = []
    pairs = [
        ("port", "inland"),
        ("industrial", "depot"),
        ("depot", "industrial"),
        ("inland", "port"),
    ]
    for i in range(job_count):
        pickup, delivery = pairs[i % len(pairs)]
        start = origin + timedelta(minutes=(i // 4) * 400 + (i % 4) * 40 + 60)
        jobs.append(
            Job(
                id=f"job-{i + 1:03}",
                reference=f"SFD-{1041 + i}",
                customer=["Demo Eastern Supply", "Demo Gulf Industries", "Demo Horizon Trading"][
                    i % 3
                ],
                pickup_site_id=pickup,
                delivery_site_id=delivery,
                pickup_window=Window(start=start, end=start + timedelta(hours=4)),
                delivery_window=Window(
                    start=start + timedelta(hours=1), end=start + timedelta(hours=8)
                ),
                equipment="flatbed" if i % 5 == 4 and team_count >= 3 else "dry_van",
                weight_kg=8000 + (i % 5) * 3000,
                revenue_minor=180000 + (i % 4) * 40000,
                priority=1 if i % 3 == 0 else 2,
            )
        )
    return Snapshot(
        tenant_id=tenant_id,
        scope_id=scope_id,
        name="Eastern depot · Synthetic planning day",
        horizon=horizon,
        sites=sites,
        resources=tuple(resources),
        teams=tuple(teams),
        jobs=tuple(jobs),
        lanes=lanes,
        costs=CostProfile(
            distance_minor_per_km=Decimal("180"), duty_minor_per_hour=Decimal("2500")
        ),
    )


def benchmark_snapshot() -> Snapshot:
    snapshot = demo_snapshot(job_count=150, team_count=50)
    # Spread known work across the 48-hour decision horizon with overlapping windows.
    origin = snapshot.horizon.start
    jobs = []
    for i, job in enumerate(snapshot.jobs):
        start = origin + timedelta(minutes=60 + (i // 15) * 240 + (i % 3) * 20)
        jobs.append(
            job.model_copy(
                update={
                    "pickup_window": Window(start=start, end=start + timedelta(hours=3)),
                    "delivery_window": Window(
                        start=start + timedelta(hours=1), end=start + timedelta(hours=8)
                    ),
                }
            )
        )
    return snapshot.model_copy(
        update={"jobs": tuple(jobs), "name": "50 teams / 150 jobs / 48 hours · Synthetic benchmark"}
    )
