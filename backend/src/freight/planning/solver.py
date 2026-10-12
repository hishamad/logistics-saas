"""Fixed-team job sequencing with explicit depot arcs and terminal movements."""

from collections import defaultdict
from decimal import Decimal
from importlib.metadata import version
from time import perf_counter
from typing import Any

from ortools.sat.python import cp_model

from freight.domain.models import Finding, Plan, Snapshot
from freight.domain.time import minute_down, minute_up
from freight.planning.context import Context
from freight.planning.routes import build_route
from freight.validation.validator import input_findings, validate_plan


def solve_plan(
    snapshot: Snapshot,
    *,
    seconds: float = 15,
    diagnostic: bool = False,
    seed: int = 7,
    hint: Plan | None = None,
) -> Plan:
    started = perf_counter()
    jobs = [j for j in snapshot.jobs if j.state == "confirmed"]
    problems = input_findings(snapshot)
    if problems:
        return Plan(
            snapshot_hash=snapshot.fingerprint,
            method="cp_sat",
            outcome="model_invalid",
            coverage="partial",
            unserved_job_ids=tuple(j.id for j in jobs),
            findings=problems,
        )
    context = Context(snapshot)
    origin = snapshot.horizon.start
    model = cp_model.CpModel()
    max_time = max(1, *(minute_down(r.availability.end, origin) for r in snapshot.resources))
    if max_time > 60 * 24 * 14:
        return Plan(
            snapshot_hash=snapshot.fingerprint,
            method="cp_sat",
            outcome="model_invalid",
            coverage="partial",
            findings=(
                Finding(
                    code="time_domain_too_large",
                    message="Resource calendars must end within 14 days of the snapshot.",
                ),
            ),
            unserved_job_ids=tuple(j.id for j in jobs),
        )
    variables: dict[str, dict[str, Any]] = {}
    choices: dict[str, list[Any]] = defaultdict(list)
    used_by_resource: dict[str, list[Any]] = defaultdict(list)
    distance_terms: list[Any] = []
    duty_terms: list[Any] = []
    preference_terms: list[Any] = []
    horizon_last_start = minute_up(snapshot.horizon.end, origin) - 1

    for t, team in enumerate(snapshot.teams):
        candidates = [j for j in jobs if context.eligible(j, team)]
        start_site, ready = context.team_start(team)
        end_site, limit = context.team_end(team)
        used = model.new_bool_var(f"used_{t}")
        depart = model.new_int_var(0, max_time, f"depart_{t}")
        finish = model.new_int_var(0, max_time, f"finish_{t}")
        duty = model.new_int_var(0, max_time, f"duty_{t}")
        terminal_move = (
            context.lane(start_site, end_site) if end_site and start_site != end_site else None
        )
        active = model.new_constant(1) if terminal_move else used
        model.add(depart >= ready).only_enforce_if(active)
        model.add(finish <= limit).only_enforce_if(active)
        model.add(finish >= depart)
        model.add(duty == finish - depart)
        if terminal_move:
            model.add(finish == depart + terminal_move.duration_minutes).only_enforce_if(used.Not())
            distance_terms.append(terminal_move.distance_m * used.Not())
        else:
            model.add(depart == 0).only_enforce_if(used.Not())
            model.add(finish == 0).only_enforce_if(used.Not())
            if any(r.kind == "required_end" and r.team_id == team.id for r in snapshot.rules):
                model.add(ready <= limit)
        intervals = [
            model.new_optional_interval_var(depart, duty, finish, active, f"duty_interval_{t}")
        ]
        for n, (busy_start, busy_end) in enumerate(context.blocked(team)):
            if busy_start < busy_end:
                intervals.append(
                    model.new_fixed_size_interval_var(
                        busy_start, busy_end - busy_start, f"blocked_{t}_{n}"
                    )
                )
        model.add_no_overlap(intervals)
        duty_terms.append(duty)
        for resource_id in team.resource_ids:
            used_by_resource[resource_id].append(active)

        # Node zero is the team's depot. Self-loops mark jobs not assigned here.
        arcs: list[tuple[int, int, Any]] = [(0, 0, used.Not())]
        present: dict[str, Any] = {}
        pickup: dict[str, Any] = {}
        delivery: dict[str, Any] = {}
        release: dict[str, Any] = {}
        edge: dict[tuple[int, int], Any] = {}
        for i, job in enumerate(candidates, 1):
            p = model.new_bool_var(f"present_{t}_{i}")
            choices[job.id].append(p)
            present[job.id] = p
            pickup[job.id] = model.new_int_var(0, max_time, f"pickup_{t}_{i}")
            delivery[job.id] = model.new_int_var(0, max_time, f"delivery_{t}_{i}")
            release[job.id] = model.new_int_var(0, max_time, f"release_{t}_{i}")
            arcs.append((i, i, p.Not()))
            model.add_implication(p, used)
            loaded = context.lane(job.pickup_site_id, job.delivery_site_id)
            model.add(pickup[job.id] >= minute_up(job.pickup_window.start, origin)).only_enforce_if(
                p
            )
            model.add(
                pickup[job.id]
                <= min(horizon_last_start, minute_down(job.pickup_window.end, origin))
            ).only_enforce_if(p)
            model.add(
                delivery[job.id] >= pickup[job.id] + job.loading_minutes + loaded.duration_minutes
            ).only_enforce_if(p)
            delivery_offset = (
                job.unloading_minutes if job.delivery_window_kind == "completion" else 0
            )
            model.add(
                delivery[job.id] + delivery_offset >= minute_up(job.delivery_window.start, origin)
            ).only_enforce_if(p)
            model.add(
                delivery[job.id] + delivery_offset <= minute_down(job.delivery_window.end, origin)
            ).only_enforce_if(p)
            model.add(
                release[job.id] == delivery[job.id] + job.unloading_minutes + job.turnaround_minutes
            ).only_enforce_if(p)
            for value in (pickup[job.id], delivery[job.id], release[job.id]):
                model.add(value == 0).only_enforce_if(p.Not())
            distance_terms.append(loaded.distance_m * p)
            for lock in snapshot.locks:
                if lock.job_id == job.id and lock.pickup_at is not None:
                    # A sub-minute lock cannot silently be moved by discretization.
                    value = minute_up(lock.pickup_at, origin)
                    if value != minute_down(lock.pickup_at, origin):
                        model.add(p == 0)
                    else:
                        model.add(pickup[job.id] == value).only_enforce_if(p)
            for rule in snapshot.rules:
                if (
                    rule.kind == "preferred_assignment"
                    and rule.strength == "soft"
                    and rule.job_id == job.id
                    and rule.team_id != team.id
                ):
                    preference_terms.append(rule.penalty_minor * p)
            first = model.new_bool_var(f"first_{t}_{i}")
            last = model.new_bool_var(f"last_{t}_{i}")
            arcs.extend([(0, i, first), (i, 0, last)])
            edge[0, i], edge[i, 0] = first, last
            inbound = context.lane(start_site, job.pickup_site_id)
            outbound = context.lane(job.delivery_site_id, end_site) if end_site else None
            model.add(pickup[job.id] >= depart + inbound.duration_minutes).only_enforce_if(first)
            model.add(
                finish == release[job.id] + (outbound.duration_minutes if outbound else 0)
            ).only_enforce_if(last)
            distance_terms.extend(
                [inbound.distance_m * first, (outbound.distance_m if outbound else 0) * last]
            )
        for i, before in enumerate(candidates, 1):
            for j, after in enumerate(candidates, 1):
                if i == j:
                    continue
                lane = context.lane(before.delivery_site_id, after.pickup_site_id)
                earliest_end = (
                    max(
                        minute_up(before.pickup_window.start, origin)
                        + before.loading_minutes
                        + context.lane(
                            before.pickup_site_id, before.delivery_site_id
                        ).duration_minutes
                        + before.unloading_minutes,
                        minute_up(before.delivery_window.start, origin)
                        + (
                            before.unloading_minutes
                            if before.delivery_window_kind == "service_start"
                            else 0
                        ),
                    )
                    + before.turnaround_minutes
                )
                if earliest_end + lane.duration_minutes > minute_down(
                    after.pickup_window.end, origin
                ):
                    continue
                follows = model.new_bool_var(f"edge_{t}_{i}_{j}")
                arcs.append((i, j, follows))
                edge[i, j] = follows
                model.add(
                    pickup[after.id] >= release[before.id] + lane.duration_minutes
                ).only_enforce_if(follows)
                distance_terms.append(lane.distance_m * follows)
        model.add_circuit(arcs)
        if candidates:
            model.add(sum(present.values()) >= used)
        else:
            model.add(used == 0)
        variables[team.id] = {
            "candidates": candidates,
            "present": present,
            "pickup": pickup,
            "delivery": delivery,
            "edge": edge,
            "depart": depart,
            "used": used,
            "finish": finish,
            "duty": duty,
            "release": release,
        }

    for variables_for_resource in used_by_resource.values():
        if len(variables_for_resource) > 1:
            model.add_at_most_one(variables_for_resource)

    served: dict[str, Any] = {}
    for job in jobs:
        variable = model.new_bool_var(f"served_{job.id}")
        model.add(sum(choices[job.id]) == variable)
        if not diagnostic or any(lock.job_id == job.id for lock in snapshot.locks):
            model.add(variable == 1)
        served[job.id] = variable

    # Only a plan checked against these exact inputs can seed the search.
    if hint is not None and hint.snapshot_hash != snapshot.fingerprint:
        hint = None
    if hint is not None:
        hint = validate_plan(snapshot, hint)
        if hint.valid and (diagnostic or hint.coverage == "complete"):
            for team in snapshot.teams:
                state = variables[team.id]
                route = sorted(
                    (a for a in hint.assignments if a.team_id == team.id), key=lambda a: a.pickup_at
                )
                activities_for_team = [a for a in hint.activities if a.team_id == team.id]
                by_id = {a.job_id: a for a in route}
                model.add_hint(state["used"], bool(route))
                depart_hint = (
                    minute_up(min(a.start for a in activities_for_team), origin)
                    if activities_for_team
                    else 0
                )
                finish_hint = (
                    minute_up(max(a.end for a in activities_for_team), origin)
                    if activities_for_team
                    else 0
                )
                for name, value in (
                    ("depart", depart_hint),
                    ("finish", finish_hint),
                    ("duty", finish_hint - depart_hint),
                ):
                    model.add_hint(state[name], value)
                nodes = {j.id: i for i, j in enumerate(state["candidates"], 1)}
                path = [0, *(nodes[a.job_id] for a in route), 0]
                selected_edges = set(zip(path, path[1:], strict=False))
                for key, literal in state["edge"].items():
                    model.add_hint(literal, key in selected_edges)
                for job in state["candidates"]:
                    assignment = by_id.get(job.id)
                    model.add_hint(state["present"][job.id], assignment is not None)
                    model.add_hint(
                        state["pickup"][job.id],
                        minute_up(assignment.pickup_at, origin) if assignment else 0,
                    )
                    delivery_hint = (
                        minute_up(assignment.delivery_at, origin)
                        - (job.unloading_minutes if job.delivery_window_kind == "completion" else 0)
                        if assignment
                        else 0
                    )
                    model.add_hint(state["delivery"][job.id], delivery_hint)
                    model.add_hint(
                        state["release"][job.id],
                        minute_up(assignment.released_at, origin) if assignment else 0,
                    )
            for job in jobs:
                model.add_hint(served[job.id], any(a.job_id == job.id for a in hint.assignments))

    # Fixed-point objective is deliberately separate from authoritative rounded
    # monetary totals. The validator recomputes financial components afterwards.
    # Aggregate before scaling: scaling each dense routing arc can overflow the
    # CP-SAT int64 objective even when every feasible route total is small.
    max_distance = max((lane.distance_m for lane in snapshot.lanes), default=0)
    total_distance = model.new_int_var(
        0, (2 * len(jobs) + 2 * len(snapshot.teams)) * max_distance, "total_distance"
    )
    total_duty = model.new_int_var(0, len(snapshot.teams) * max_time, "total_duty")
    total_penalty = model.new_int_var(
        0, sum(r.penalty_minor for r in snapshot.rules if r.strength == "soft"), "total_penalty"
    )
    model.add(total_distance == sum(distance_terms))
    model.add(total_duty == sum(duty_terms))
    model.add(total_penalty == sum(preference_terms))
    if hint is not None and hint.valid and (diagnostic or hint.coverage == "complete"):
        model.add_hint(total_distance, sum(a.distance_m for a in hint.activities))
        model.add_hint(
            total_duty, sum(int((a.end - a.start).total_seconds() // 60) for a in hint.activities)
        )
        model.add_hint(total_penalty, hint.objective_penalty_minor)
    if snapshot.costs.complete:
        distance_rate = int((snapshot.costs.distance_minor_per_km or Decimal(0)) * 100) * 60
        duty_rate = int((snapshot.costs.duty_minor_per_hour or Decimal(0)) * 100) * 1000
        economic = (
            total_distance * distance_rate + total_duty * duty_rate + total_penalty * 6_000_000
        )
    else:
        # Without money rates use distance first, duty second. Never add metres
        # to currency penalties; input checks require rates for such rules.
        economic = total_distance * (len(snapshot.teams) * max_time + 1) + total_duty
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = seed
    solver.parameters.num_search_workers = 1
    # A complete independent incumbent makes a long presolve unnecessary for the
    # first bounded improvement search on large dense routing models.
    if hint is not None and hint.valid and hint.coverage == "complete" and len(jobs) > 40:
        solver.parameters.cp_model_presolve = False
    status = cp_model.UNKNOWN
    model_stats = {
        "variables": len(model.proto.variables),
        "constraints": len(model.proto.constraints),
        "candidate_assignments": sum(len(v["candidates"]) for v in variables.values()),
        "sequence_arcs": sum(len(v["edge"]) for v in variables.values()),
        "model_build_ms": round((perf_counter() - started) * 1000),
    }
    all_stages_optimal = True
    incumbent: cp_model.CpSolver | None = None
    if diagnostic:
        # True lexicographic coverage; never let a cash benefit drop an obligation.
        for priority in sorted({j.priority for j in jobs}):
            remaining = seconds - (perf_counter() - started)
            if remaining <= 0:
                break
            score = sum(served[j.id] for j in jobs if j.priority == priority)
            model.maximize(score)
            solver.parameters.max_time_in_seconds = max(0.01, remaining / 2)
            status = solver.solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                break
            incumbent = solver
            all_stages_optimal &= status == cp_model.OPTIMAL
            model.add(score == solver.value(score))
            solver = cp_model.CpSolver()
            solver.parameters.random_seed = seed
            solver.parameters.num_search_workers = 1
    remaining = seconds - (perf_counter() - started)
    if diagnostic and remaining <= 0 and incumbent is not None:
        status = cp_model.UNKNOWN
    if not diagnostic or not jobs or status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if remaining > 0:
            model.minimize(economic)
            solver.parameters.max_time_in_seconds = max(0.01, remaining)
            status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE) and incumbent is not None:
        solver, status, all_stages_optimal = incumbent, cp_model.FEASIBLE, False
    mapping = {
        cp_model.OPTIMAL: "optimal",
        cp_model.FEASIBLE: "feasible",
        cp_model.INFEASIBLE: "proven_infeasible",
        cp_model.MODEL_INVALID: "model_invalid",
        cp_model.UNKNOWN: "unknown",
    }
    outcome = mapping[status]
    if outcome == "optimal" and not all_stages_optimal:
        outcome = "feasible"
    assignments, activities = [], []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for team in snapshot.teams:
            state = variables[team.id]
            if not solver.boolean_value(state["used"]):
                # Explicit terminal requirements can still require an empty move.
                start_site, ready = context.team_start(team)
                end_site, _ = context.team_end(team)
                if end_site and start_site != end_site:
                    a, b = build_route(snapshot, team, [], solver.value(state["depart"]))
                    assignments.extend(a)
                    activities.extend(b)
                continue
            sequence = []
            current = 0
            while True:
                successor = next(
                    j
                    for (i, j), literal in state["edge"].items()
                    if i == current and solver.boolean_value(literal)
                )
                if successor == 0:
                    break
                sequence.append(state["candidates"][successor - 1])
                current = successor
            a, b = build_route(
                snapshot,
                team,
                sequence,
                solver.value(state["depart"]),
                {j.id: solver.value(state["pickup"][j.id]) for j in sequence},
                {j.id: solver.value(state["delivery"][j.id]) for j in sequence},
            )
            assignments.extend(a)
            activities.extend(b)
    assigned = {a.job_id for a in assignments}
    unserved = tuple(j.id for j in jobs if j.id not in assigned)
    result = Plan(
        snapshot_hash=snapshot.fingerprint,
        method="cp_sat",
        outcome=outcome,
        coverage="partial" if unserved else "complete",
        assignments=tuple(assignments),
        activities=tuple(activities),
        unserved_job_ids=unserved,
        diagnostic=diagnostic,
        runtime_ms=round((perf_counter() - started) * 1000),
        solver_version=version("ortools"),
        objective_bound=float(solver.best_objective_bound)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) and solver is not incumbent
        else None,
        model_stats=model_stats,
    )
    return validate_plan(snapshot, result)
