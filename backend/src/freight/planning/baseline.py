from time import perf_counter

from freight.domain.models import Job, Plan, Snapshot, Team
from freight.domain.time import minute_down
from freight.planning.context import Context
from freight.planning.routes import build_route
from freight.validation.validator import input_findings, validate_plan


def assemble(snapshot: Snapshot, routes: dict[str, list[Job]], departures: dict[str, int]) -> Plan:
    assignments, activities = [], []
    for team in snapshot.teams:
        route = routes.get(team.id, [])
        # Required terminal movements apply even to a team with no assigned jobs.
        terminal, _ = Context(snapshot).team_end(team)
        start_site, ready = Context(snapshot).team_start(team)
        if route or (terminal and terminal != start_site):
            a, b = build_route(snapshot, team, route, departures.get(team.id, ready))
            assignments.extend(a)
            activities.extend(b)
    assigned = {a.job_id for a in assignments}
    unserved = tuple(j.id for j in snapshot.jobs if j.state == "confirmed" and j.id not in assigned)
    return validate_plan(
        snapshot,
        Plan(
            snapshot_hash=snapshot.fingerprint,
            method="baseline",
            outcome="feasible",
            coverage="partial" if unserved else "complete",
            assignments=tuple(assignments),
            activities=tuple(activities),
            unserved_job_ids=unserved,
            diagnostic=bool(unserved),
        ),
    )


def departure_options(context: Context, team: Team, sequence: list[Job]) -> list[int]:
    site, ready = context.team_start(team)
    options = {ready}
    if sequence:
        first = sequence[0]
        travel = context.lane(site, first.pickup_site_id).duration_minutes
        options.add(
            max(
                ready,
                minute_down(first.pickup_window.start, context.snapshot.horizon.start) - travel,
            )
        )
    options.update(end for _, end in context.blocked(team) if end >= ready)
    return sorted(options)


def baseline_plan(snapshot: Snapshot, *, seconds: float = 30) -> Plan:
    started = perf_counter()
    problems = input_findings(snapshot)
    if problems:
        return Plan(
            snapshot_hash=snapshot.fingerprint,
            method="baseline",
            outcome="model_invalid",
            coverage="partial",
            unserved_job_ids=tuple(j.id for j in snapshot.jobs if j.state == "confirmed"),
            findings=problems,
        )
    context = Context(snapshot)
    routes: dict[str, list[Job]] = {team.id: [] for team in snapshot.teams}
    departures = {team.id: context.team_start(team)[1] for team in snapshot.teams}
    route_scores: dict[str, int] = {}

    def route_candidate(team: Team, sequence: list[Job], departure: int) -> Plan:
        # Check the changed route independently, then check the whole fleet once
        # at the end. Cross-team resource use is guarded explicitly below.
        job_ids = {j.id for j in sequence}
        subset = snapshot.model_copy(
            update={
                "jobs": tuple(sequence),
                "teams": (team,),
                "resources": tuple(context.resources[r] for r in team.resource_ids),
                "rules": tuple(
                    r
                    for r in snapshot.rules
                    if (r.team_id is None or r.team_id == team.id)
                    and (r.resource_id is None or r.resource_id in team.resource_ids)
                    and (r.job_id is None or r.job_id in job_ids)
                ),
                "locks": tuple(lock for lock in snapshot.locks if lock.job_id in job_ids),
            }
        )
        return assemble(subset, {team.id: sequence}, {team.id: departure})

    def score(plan: Plan) -> int:
        assert plan.costs is not None
        return (
            int(
                (plan.costs.total_minor if plan.costs.available else plan.costs.empty_distance_m)
                or 0
            )
            + plan.objective_penalty_minor
        )

    for team in snapshot.teams:
        # An idle required-end movement also has to avoid calendar blocks.
        options = [
            (departure, route_candidate(team, [], departure))
            for departure in departure_options(context, team, [])
        ]
        valid = [(score(plan), departure, plan) for departure, plan in options if plan.valid]
        if valid:
            _, departures[team.id], initial = min(valid, key=lambda item: item[:2])
        else:
            initial = options[0][1]
        route_scores[team.id] = score(initial)
    # Locked jobs enter first so a greedy choice cannot displace a commitment.
    locked = {lock.job_id for lock in snapshot.locks}
    jobs = sorted(
        context.jobs.values(),
        key=lambda j: (j.id not in locked, j.priority, j.pickup_window.end, j.id),
    )
    for job in jobs:
        if perf_counter() - started >= seconds:
            break
        best: tuple[int, str, int, int, Plan] | None = None
        for team in snapshot.teams:
            if perf_counter() - started >= seconds:
                break
            if not context.eligible(job, team):
                continue
            if any(
                other.id != team.id
                and set(team.resource_ids) & set(other.resource_ids)
                and (
                    routes[other.id]
                    or (
                        context.team_end(other)[0] is not None
                        and context.team_end(other)[0] != context.team_start(other)[0]
                    )
                )
                for other in snapshot.teams
            ):
                continue
            for position in range(len(routes[team.id]) + 1):
                if perf_counter() - started >= seconds:
                    break
                sequence = [*routes[team.id][:position], job, *routes[team.id][position:]]
                for departure in departure_options(context, team, sequence):
                    if perf_counter() - started >= seconds:
                        break
                    candidate = route_candidate(team, sequence, departure)
                    if not candidate.valid or candidate.costs is None:
                        continue
                    ranking = (
                        score(candidate) - route_scores[team.id],
                        team.id,
                        position,
                        departure,
                    )
                    if best is None or ranking < best[:4]:
                        best = (*ranking, candidate)
        if best:
            _, team_id, position, departure, candidate = best
            routes[team_id].insert(position, job)
            departures[team_id] = departure
            route_scores[team_id] = score(candidate)
    result = assemble(snapshot, routes, departures)
    return result.model_copy(update={"runtime_ms": round((perf_counter() - started) * 1000)})
