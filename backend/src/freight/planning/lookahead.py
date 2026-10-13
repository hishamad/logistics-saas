"""What is a truck worth at each site when the plan ends?

A small time-expanded network model of the days after the planning horizon:
trucks wait, reposition empty, or carry expected loads (rate-limited per lane)
for a profit. The total profit the fleet can earn depends on where its trucks
start. Varying the number of trucks at one site while the rest of the fleet
stays where the current plan leaves it gives that site's value curve: what the
1st, 2nd, 3rd ... truck ending there is worth. The curve flattens as a site
fills up, so the planner does not send every truck to the same attractive place.
This is the separable, concave value function of approximate dynamic programming
for truckload fleets (Powell and co-authors), estimated with a linear program.

The forecast is the demand pattern of known jobs, assumed to repeat. With a real
carrier it should come from several weeks of history instead.
"""

from collections import Counter
from dataclasses import dataclass
from math import ceil
from time import perf_counter

from ortools.linear_solver import pywraplp

from freight.domain.models import Plan, Snapshot
from freight.planning.engine import Engine, plan_lns, routes_of


@dataclass(frozen=True)
class LaneForecast:
    pickup: str
    delivery: str
    loads_per_day: float
    revenue_minor: float
    service_minutes: float  # loading + unloading + turnaround


def forecast_from_jobs(snapshot: Snapshot) -> list[LaneForecast]:
    """Treat the scenario's own confirmed and offered jobs as the typical daily pattern."""
    days = max(1.0, (snapshot.horizon.end - snapshot.horizon.start).total_seconds() / 86400)
    grouped: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for job in snapshot.jobs:
        if job.state == "cancelled" or job.revenue_minor is None:
            continue
        service = job.loading_minutes + job.unloading_minutes + job.turnaround_minutes
        key = (job.pickup_site_id, job.delivery_site_id)
        grouped.setdefault(key, []).append((float(job.revenue_minor), float(service)))
    return [
        LaneForecast(
            pickup=a,
            delivery=b,
            loads_per_day=len(rows) / days,
            revenue_minor=sum(r for r, _ in rows) / len(rows),
            service_minutes=sum(s for _, s in rows) / len(rows),
        )
        for (a, b), rows in grouped.items()
    ]


class ValueModel:
    """The look-ahead linear program, built once and re-solved for different fleets."""

    def __init__(
        self,
        snapshot: Snapshot,
        forecast: list[LaneForecast],
        hours: int = 72,
        bucket_hours: int = 12,
    ) -> None:
        engine = Engine(snapshot)
        self.sites = [s.id for s in snapshot.sites]
        buckets = hours // bucket_hours
        size = bucket_hours * 60

        def steps(minutes: float) -> int:
            return max(1, ceil(minutes / size))

        solver = pywraplp.Solver.CreateSolver("GLOP")
        if solver is None:
            raise RuntimeError("The GLOP linear solver is unavailable")
        self.solver = solver
        outflow: dict[tuple[str, int], list[pywraplp.Variable]] = {}
        inflow: dict[tuple[str, int], list[pywraplp.Variable]] = {}
        objective = solver.Objective()

        def move(a: str, k: int, b: str, arrive: int, profit: float, cap: float | None) -> None:
            variable = solver.NumVar(0, solver.infinity() if cap is None else cap, "")
            outflow.setdefault((a, k), []).append(variable)
            if arrive < buckets:
                inflow.setdefault((b, arrive), []).append(variable)
            objective.SetCoefficient(variable, profit)

        for k in range(buckets):
            for a in self.sites:
                move(a, k, a, k + 1, 0.0, None)  # wait, or leave the window at no value
                for b in self.sites:
                    if a == b:
                        continue
                    drive, metres = engine.lane(a, b)
                    arrive = k + steps(engine.elapsed(drive))
                    if arrive < buckets:  # repositioning only helps if it lands in time
                        cost = metres / 1000 * engine.per_km + drive * engine.per_minute
                        move(a, k, b, arrive, -cost, None)
            for lane in forecast:
                drive, metres = engine.lane(lane.pickup, lane.delivery)
                cost = (
                    metres / 1000 * engine.per_km
                    + (drive + lane.service_minutes) * engine.per_minute
                )
                arrive = k + steps(engine.elapsed(drive) + lane.service_minutes)
                capacity = lane.loads_per_day * bucket_hours / 24
                move(lane.pickup, k, lane.delivery, arrive, lane.revenue_minor - cost, capacity)
        objective.SetMaximization()
        self.start: dict[str, pywraplp.Constraint] = {}
        for a in self.sites:
            for k in range(buckets):
                constraint = solver.Constraint(0, 0)
                for variable in outflow.get((a, k), []):
                    constraint.SetCoefficient(variable, 1)
                for variable in inflow.get((a, k), []):
                    constraint.SetCoefficient(variable, -1)
                if k == 0:
                    self.start[a] = constraint

    def profit(self, fleet: Counter[str]) -> float:
        for site, constraint in self.start.items():
            constraint.SetBounds(fleet.get(site, 0), fleet.get(site, 0))
        if self.solver.Solve() != pywraplp.Solver.OPTIMAL:
            raise RuntimeError("The look-ahead model did not solve")
        return float(self.solver.Objective().Value())

    def value_curves(self, fleet: Counter[str], extra: int = 8) -> dict[str, tuple[int, ...]]:
        """Per site, the value (minor units) of the 1st, 2nd, ... truck ending there.

        The rest of the fleet stays as given. Counts between solved points are
        interpolated linearly; the curve never increases.
        """
        curves: dict[str, tuple[int, ...]] = {}
        for site in self.sites:
            top = fleet.get(site, 0) + extra
            grid = sorted(
                {0, 1, 2, 4, 8, 16, 32, 64, fleet.get(site, 0), top} & set(range(top + 1))
            )
            others = fleet.copy()
            values = {}
            for n in grid:
                others[site] = n
                values[n] = self.profit(others)
            slopes: list[int] = []
            for low, high in zip(grid, grid[1:], strict=False):
                step = (values[high] - values[low]) / (high - low)
                slopes += [round(step)] * (high - low)
            for i in range(1, len(slopes)):
                slopes[i] = min(slopes[i], slopes[i - 1])
            curves[site] = tuple(max(0, s) for s in slopes)
        return curves


def end_positions(snapshot: Snapshot, plan: Plan) -> Counter[str]:
    """Where each team is when the plan ends (home if it has no activities)."""
    last: dict[str, tuple[object, str]] = {}
    for activity in plan.activities:
        if activity.team_id not in last or activity.end >= last[activity.team_id][0]:  # type: ignore[operator]
            last[activity.team_id] = (activity.end, activity.to_site_id)
    return Counter(
        last[team.id][1] if team.id in last else snapshot.home_of(team) for team in snapshot.teams
    )


def plan_with_lookahead(
    snapshot: Snapshot, *, seconds: float = 30, seed: int = 7
) -> tuple[Snapshot, Plan]:
    """Plan once to see where trucks end, value those positions, then plan with the values.

    Returns the snapshot including its end values: the plan belongs to that snapshot.
    """
    started = perf_counter()
    first = plan_lns(snapshot, seconds=seconds * 0.3, seed=seed)
    model = ValueModel(snapshot, forecast_from_jobs(snapshot))
    curves = model.value_curves(end_positions(snapshot, first))
    valued = snapshot.model_copy(update={"end_values": curves})
    remaining = max(1.0, seconds - (perf_counter() - started))
    return valued, plan_lns(valued, seconds=remaining, seed=seed, initial=routes_of(first))
