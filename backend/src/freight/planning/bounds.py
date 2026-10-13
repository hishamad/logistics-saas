"""A lower bound on the modeled cost of serving a given set of jobs.

Relaxation: keep only "which job may follow which" and drop the clock along a
truck's chain, driver rests, trips home and waiting. Every job then needs one
predecessor (a truck leaving its depot, or an earlier job) and one successor
(a later job, or the end of a chain). Choosing the cheapest such linking is a
min-cost flow problem. Each relaxation step only removes restrictions, so no
real plan serving the same jobs can cost less: the result is a valid floor.

    upper bound on suboptimality = (plan cost - bound) / plan cost
"""

from math import floor

from ortools.graph.python import min_cost_flow

from freight.domain.models import Snapshot
from freight.planning.engine import Engine

SCALE = 10  # cost units per minor unit; arc costs are rounded down to stay a valid bound
ROUNDING = 1.0  # minor units of slack for the validator's per-component rounding


def lower_bound(snapshot: Snapshot, job_ids: set[str]) -> float | None:
    """Minor units no plan serving exactly ``job_ids`` can undercut; None if relaxed-infeasible."""
    e = Engine(snapshot)
    jobs = [e.jobs[j] for j in sorted(job_ids)]
    teams = list(e.teams.values())

    def travel(a: str, b: str) -> float:
        minutes, metres = e.lane(a, b)
        return metres / 1000 * e.per_km + minutes * e.per_minute

    eligible = {j.id: frozenset(e.eligible[j.id]) for j in jobs}
    shared: dict[tuple[frozenset[str], frozenset[str]], bool] = {}

    def compatible(a: str, b: str) -> bool:
        key = (eligible[a], eligible[b])
        if key not in shared:
            shared[key] = not key[0].isdisjoint(key[1])
        return shared[key]

    fixed = 0.0
    release: dict[str, int] = {}
    for job in jobs:
        pickup_open, _, delivery_open, _ = e.window[job.id]
        locked = e.locks.get(job.id)
        if locked and locked[1] is not None:
            pickup_open = locked[1]
        loaded_minutes, loaded_metres = e.lane(job.pickup_site_id, job.delivery_site_id)
        service = job.loading_minutes + job.unloading_minutes + job.turnaround_minutes
        fixed += loaded_metres / 1000 * e.per_km + (loaded_minutes + service) * e.per_minute
        release[job.id] = (
            max(pickup_open + job.loading_minutes + e.elapsed(loaded_minutes), delivery_open)
            + job.unloading_minutes
            + job.turnaround_minutes
        )

    def latest_pickup(job_id: str) -> int:
        locked = e.locks.get(job_id)
        return locked[1] if locked and locked[1] is not None else e.window[job_id][1]

    # Nodes: team outlets, job outlets (suppliers); job inlets, one sink (demand).
    flow = min_cost_flow.SimpleMinCostFlow()
    team_node = {t.id: i for i, t in enumerate(teams)}
    out_node = {j.id: len(teams) + i for i, j in enumerate(jobs)}
    in_node = {j.id: len(teams) + len(jobs) + i for i, j in enumerate(jobs)}
    sink = len(teams) + 2 * len(jobs)

    def arc(tail: int, head: int, cost: float) -> None:
        flow.add_arc_with_capacity_and_unit_cost(tail, head, 1, floor(cost * SCALE))

    for team in teams:
        node = team_node[team.id]
        flow.set_node_supply(node, 1)
        idle = travel(team.start, team.end_site) if team.end_site else 0.0
        arc(node, sink, idle)
        for job in jobs:
            if team.id not in eligible[job.id]:
                continue
            reach = team.ready + e.elapsed(e.lane(team.start, job.pickup_site_id)[0])
            if reach <= latest_pickup(job.id):
                arc(node, in_node[job.id], travel(team.start, job.pickup_site_id))
    for job in jobs:
        flow.set_node_supply(out_node[job.id], 1)
        flow.set_node_supply(in_node[job.id], -1)
        ends = [
            travel(job.delivery_site_id, t.end_site) if t.end_site else 0.0
            for t in teams
            if t.id in eligible[job.id]
        ]
        arc(out_node[job.id], sink, min(ends, default=0.0))
        for following in jobs:
            if following.id == job.id or not compatible(job.id, following.id):
                continue
            gap = e.elapsed(e.lane(job.delivery_site_id, following.pickup_site_id)[0])
            if release[job.id] + gap <= latest_pickup(following.id):
                arc(
                    out_node[job.id],
                    in_node[following.id],
                    travel(job.delivery_site_id, following.pickup_site_id),
                )
    flow.set_node_supply(sink, -len(teams))
    if flow.solve() != flow.OPTIMAL:
        return None
    # The validator rounds distance and duty to whole minor units separately, so a
    # plan's reported cost can sit up to one unit per component below the exact value.
    return fixed + int(flow.optimal_cost()) / SCALE - ROUNDING
