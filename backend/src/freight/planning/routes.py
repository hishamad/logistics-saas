from datetime import timedelta

from freight.domain.models import Activity, Assignment, Job, Snapshot, Team
from freight.domain.time import instant, minute_up
from freight.planning.context import Context


def build_route(
    snapshot: Snapshot,
    team: Team,
    sequence: list[Job],
    departure_minute: int,
    pickup_minutes: dict[str, int] | None = None,
    delivery_start_minutes: dict[str, int] | None = None,
) -> tuple[list[Assignment], list[Activity]]:
    """Materialize a proposed route. This is construction, never validation."""
    context = Context(snapshot)
    origin = snapshot.horizon.start
    location, _ = context.team_start(team)
    clock = instant(departure_minute, origin)
    activities: list[Activity] = []
    assignments: list[Assignment] = []

    def activity(
        kind: str, end_site: str, minutes: int, job_id: str | None = None, distance: int = 0
    ) -> None:
        nonlocal clock, location
        end = clock + timedelta(minutes=minutes)
        activities.append(
            Activity(
                team_id=team.id,
                kind=kind,
                from_site_id=location,
                to_site_id=end_site,
                start=clock,
                end=end,
                job_id=job_id,
                distance_m=distance,
            )
        )
        clock, location = end, end_site

    for job in sequence:
        empty = context.lane(location, job.pickup_site_id)
        if empty.duration_minutes or empty.distance_m or location != job.pickup_site_id:
            activity("empty", job.pickup_site_id, empty.duration_minutes, distance=empty.distance_m)
        pickup = (
            instant(pickup_minutes[job.id], origin)
            if pickup_minutes
            else max(clock, instant(minute_up(job.pickup_window.start, origin), origin))
        )
        if pickup_minutes is None:
            locked_time = next(
                (
                    lock.pickup_at
                    for lock in snapshot.locks
                    if lock.job_id == job.id and lock.pickup_at is not None
                ),
                None,
            )
            if locked_time is not None:
                pickup = locked_time
        if pickup > clock:
            activity("waiting", location, int((pickup - clock).total_seconds() // 60))
        pickup = clock
        activity("loading", location, job.loading_minutes, job.id)
        loaded = context.lane(job.pickup_site_id, job.delivery_site_id)
        activity("loaded", job.delivery_site_id, loaded.duration_minutes, job.id, loaded.distance_m)
        earliest = instant(minute_up(job.delivery_window.start, origin), origin)
        if job.delivery_window_kind == "completion":
            earliest -= timedelta(minutes=job.unloading_minutes)
        unloading = (
            instant(delivery_start_minutes[job.id], origin)
            if delivery_start_minutes
            else max(clock, earliest)
        )
        if unloading > clock:
            activity("waiting", location, int((unloading - clock).total_seconds() // 60))
        delivery_start = clock
        activity("unloading", location, job.unloading_minutes, job.id)
        delivery = delivery_start if job.delivery_window_kind == "service_start" else clock
        activity("turnaround", location, job.turnaround_minutes, job.id)
        assignments.append(
            Assignment(
                job_id=job.id,
                team_id=team.id,
                pickup_at=pickup,
                delivery_at=delivery,
                released_at=clock,
            )
        )
    terminal, _ = context.team_end(team)
    if terminal is not None and terminal != location:
        lane = context.lane(location, terminal)
        activity("empty", terminal, lane.duration_minutes, distance=lane.distance_m)
    return assignments, activities
