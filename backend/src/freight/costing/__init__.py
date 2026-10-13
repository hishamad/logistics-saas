from decimal import ROUND_HALF_UP, Decimal

from freight.domain.models import Activity, CostBreakdown, CostProfile


def calculate_cost(activities: tuple[Activity, ...], profile: CostProfile) -> CostBreakdown:
    """Round each aggregate cost component once, in minor currency units.

    Duty includes loading, driving, waiting, unloading and turnaround. Rest
    and on-road pauses are not paid duty. The per-distance component includes
    fuel. No optimization penalties are money.
    """
    empty = sum(a.distance_m for a in activities if a.kind == "empty")
    loaded = sum(a.distance_m for a in activities if a.kind == "loaded")
    seconds = sum(
        int((a.end - a.start).total_seconds()) - a.paused_seconds
        for a in activities
        if a.kind != "rest"
    )
    distance_minor = duty_minor = None
    if profile.distance_minor_per_km is not None:
        distance_minor = int(
            (Decimal(empty + loaded) * profile.distance_minor_per_km / 1000).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
        )
    if profile.duty_minor_per_hour is not None:
        duty_minor = int(
            (Decimal(seconds) * profile.duty_minor_per_hour / 3600).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
        )
    total = None if distance_minor is None or duty_minor is None else distance_minor + duty_minor
    return CostBreakdown(
        available=profile.complete,
        distance_minor=distance_minor,
        duty_minor=duty_minor,
        total_minor=total,
        empty_distance_m=empty,
        loaded_distance_m=loaded,
        duty_minutes=(seconds + 59) // 60,
        exclusions=profile.exclusions,
    )
