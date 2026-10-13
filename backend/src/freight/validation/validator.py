"""Independent checking of final activities; does not import planning code."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import pairwise

from freight.costing import calculate_cost
from freight.domain.models import Activity, DrivingRules, Finding, Plan, Snapshot
from freight.domain.time import overlaps


def work_intervals(activity: Activity) -> list[tuple[datetime, datetime]]:
    """Periods in which the team is working: travel minus pauses; rest is not work."""
    if activity.kind == "rest":
        return []
    intervals, cursor = [], activity.start
    for pause in sorted(activity.pauses, key=lambda p: p.start):
        intervals.append((cursor, pause.start))
        cursor = pause.end
    intervals.append((cursor, activity.end))
    return [(start, end) for start, end in intervals if start < end]


def driving_findings(rules: DrivingRules, route: list[Activity]) -> list[tuple[str, str]]:
    """Sweep one team's ordered activities and check driving-hours limits.

    Contiguous non-work time (waiting, rest, pauses, gaps) of at least the
    break length resets continuous driving; at least the daily rest resets the
    driving day and its duty span.
    """
    segments: list[tuple[datetime, datetime, str]] = []
    for activity in route:
        if activity.kind in ("waiting", "rest"):
            segments.append((activity.start, activity.end, "idle"))
            continue
        kind = "drive" if activity.kind in ("empty", "loaded") else "work"
        cursor = activity.start
        for pause in sorted(activity.pauses, key=lambda p: p.start):
            segments.append((cursor, pause.start, kind))
            segments.append((pause.start, pause.end, "idle"))
            cursor = pause.end
        segments.append((cursor, activity.end, kind))
    problems: list[tuple[str, str]] = []
    idle = float("inf")
    continuous = daily = 0.0
    span_start: datetime | None = None
    previous_end: datetime | None = None
    for start, end, kind in segments:
        if previous_end is not None and start > previous_end:
            idle += (start - previous_end).total_seconds() / 60
        previous_end = max(end, previous_end) if previous_end else end
        minutes = (end - start).total_seconds() / 60
        if kind == "idle":
            idle += minutes
            continue
        if minutes <= 0:
            continue
        if idle >= rules.break_minutes:
            continuous = 0
        if idle >= rules.daily_rest_minutes:
            daily, span_start = 0, None
        idle = 0
        span_start = span_start or start
        if kind == "drive":
            continuous += minutes
            daily += minutes
            if continuous > rules.max_continuous_driving_minutes:
                problems.append(("continuous_driving", "Driving continues past the break limit."))
            if daily > rules.max_daily_driving_minutes:
                problems.append(("daily_driving", "Daily driving exceeds the limit."))
        if (end - span_start).total_seconds() / 60 > rules.max_duty_span_minutes:
            problems.append(("duty_span", "A working day exceeds the maximum duty span."))
    return problems


def input_findings(snapshot: Snapshot) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    origin = snapshot.horizon.start
    if not snapshot.costs.complete and any(
        r.strength == "soft" and r.penalty_minor > 0 for r in snapshot.rules
    ):
        findings.append(
            Finding(
                code="missing_preference_costs",
                message="Supply both material cost rates before optimizing monetary preference penalties.",
            )
        )
    for resource in snapshot.resources:
        age = (origin - resource.confirmed_at).total_seconds() / 60
        if age > snapshot.freshness_minutes or age < 0:
            findings.append(
                Finding(
                    code="stale_resource_state",
                    message=f"Confirm availability for {resource.name} at the planning time.",
                    entity_ids=(resource.id,),
                )
            )
    lanes = {(lane.from_site_id, lane.to_site_id) for lane in snapshot.lanes}
    for start in snapshot.sites:
        for end in snapshot.sites:
            if start.id != end.id and (start.id, end.id) not in lanes:
                findings.append(
                    Finding(
                        code="missing_lane",
                        message=f"No approved travel estimate from {start.name} to {end.name}.",
                        entity_ids=(start.id, end.id),
                    )
                )
    for job in snapshot.jobs:
        if job.state == "confirmed" and job.pickup_window.start >= snapshot.horizon.end:
            findings.append(
                Finding(
                    code="outside_horizon",
                    message=f"{job.reference} starts outside this decision horizon. Extend the horizon or review the job set.",
                    entity_ids=(job.id,),
                )
            )
    for lock in snapshot.locks:
        if next(j for j in snapshot.jobs if j.id == lock.job_id).state != "confirmed":
            findings.append(
                Finding(
                    code="invalid_lock",
                    message="Only confirmed jobs can be locked.",
                    entity_ids=(lock.job_id,),
                )
            )
    for team in snapshot.teams:
        terminals = {
            r.site_id for r in snapshot.rules if r.kind == "required_end" and r.team_id == team.id
        }
        if len(terminals) > 1:
            findings.append(
                Finding(
                    code="conflicting_terminals",
                    message="A team has conflicting required end sites.",
                    entity_ids=(team.id,),
                )
            )
    return tuple(findings)


def validate_plan(snapshot: Snapshot, plan: Plan) -> Plan:
    findings = list(input_findings(snapshot))
    jobs = {job.id: job for job in snapshot.jobs}
    teams = {team.id: team for team in snapshot.teams}
    resources = {r.id: r for r in snapshot.resources}
    sites = {s.id for s in snapshot.sites}
    lanes = {(lane.from_site_id, lane.to_site_id): lane for lane in snapshot.lanes}
    by_job: dict[str, list[Activity]] = defaultdict(list)
    by_team: dict[str, list[Activity]] = defaultdict(list)
    by_resource: dict[str, list[Activity]] = defaultdict(list)

    def fail(code: str, message: str, *ids: str) -> None:
        findings.append(Finding(code=code, message=message, entity_ids=tuple(ids)))

    if plan.snapshot_hash != snapshot.fingerprint:
        fail("snapshot_mismatch", "This plan belongs to a different planning snapshot.")
    counts = Counter(a.job_id for a in plan.assignments)
    for job_id, count in counts.items():
        if count != 1:
            fail("duplicate_assignment", "A job has multiple assignments.", job_id)
    expected = {j.id for j in snapshot.jobs if j.state == "confirmed"}
    allowed = expected | {j.id for j in snapshot.jobs if j.state == "offered"}
    actual = set(counts)
    if actual - allowed:
        fail(
            "unexpected_job",
            "An assignment refers to an unknown or cancelled job.",
            *sorted(actual - allowed),
        )
    missing = expected - actual
    actual &= allowed
    if missing and not plan.diagnostic and plan.outcome in ("feasible", "optimal"):
        fail(
            "strict_coverage",
            "A strict plan must cover every confirmed obligation. Partial coverage must be explicitly diagnostic.",
            *sorted(missing),
        )
    if set(plan.unserved_job_ids) != missing or len(set(plan.unserved_job_ids)) != len(
        plan.unserved_job_ids
    ):
        fail("coverage_mismatch", "Unserved work does not match confirmed obligations.")
    if plan.coverage != ("partial" if missing else "complete"):
        fail("coverage_mismatch", "The coverage label does not match the assignments.")

    for activity in plan.activities:
        if activity.team_id not in teams:
            fail("unknown_team", "An activity refers to an unknown team.", activity.team_id)
            continue
        if activity.start > activity.end or activity.start < snapshot.horizon.start:
            fail(
                "invalid_activity_time",
                "Activity times are reversed or precede the snapshot.",
                activity.team_id,
            )
        if activity.from_site_id not in sites or activity.to_site_id not in sites:
            fail("unknown_site", "Activity location is unknown.", activity.team_id)
        if activity.job_id is not None:
            by_job[activity.job_id].append(activity)
            if activity.job_id not in actual:
                fail(
                    "orphan_activity", "Activity has no corresponding assignment.", activity.job_id
                )
        if (
            activity.kind in ("loading", "loaded", "unloading", "turnaround")
            and activity.job_id is None
        ):
            fail(
                "missing_activity_job",
                "Service and loaded movement require a job.",
                activity.team_id,
            )
        if activity.kind in ("empty", "loaded"):
            same_site = activity.from_site_id == activity.to_site_id
            lane = lanes.get((activity.from_site_id, activity.to_site_id))
            duration = 0 if same_site else lane.duration_minutes if lane else None
            distance = 0 if same_site else lane.distance_m if lane else None
            pauses = sorted(activity.pauses, key=lambda p: p.start)
            if any(
                p.start >= p.end or p.start <= activity.start or p.end >= activity.end
                for p in pauses
            ) or any(a.end > b.start for a, b in pairwise(pauses)):
                fail(
                    "invalid_pause",
                    "Pauses must lie inside the drive without overlapping.",
                    activity.team_id,
                )
            if duration is None or distance is None:
                fail("missing_lane", "Travel has no known estimate.", activity.team_id)
            elif activity.distance_m != distance or activity.end - activity.start - timedelta(
                seconds=activity.paused_seconds
            ) < timedelta(minutes=duration):
                fail(
                    "invalid_travel",
                    "Movement distance or time disagrees with the lane estimate.",
                    activity.team_id,
                )
        elif activity.pauses:
            fail("invalid_pause", "Only travel can contain pauses.", activity.team_id)
        elif activity.from_site_id != activity.to_site_id or activity.distance_m != 0:
            fail(
                "invalid_stationary_activity",
                "A stationary activity cannot change location or incur distance.",
                activity.team_id,
            )
        by_team[activity.team_id].append(activity)
        for resource_id in teams[activity.team_id].resource_ids:
            by_resource[resource_id].append(activity)
            resource = resources[resource_id]
            if (
                activity.start < resource.availability.start
                or activity.end > resource.availability.end
            ):
                fail(
                    "resource_unavailable",
                    "Activity lies outside resource availability.",
                    resource_id,
                )
            for window in resource.unavailable:
                if any(
                    overlaps(start, end, window.start, window.end)
                    for start, end in work_intervals(activity)
                ):
                    fail(
                        "resource_unavailable",
                        "Activity overlaps a resource calendar exception.",
                        resource_id,
                    )

    for team_id, activities in by_team.items():
        route = sorted(activities, key=lambda a: (a.start, a.end))
        location = resources[teams[team_id].tractor_id].site_id
        previous_end = snapshot.horizon.start
        for index, activity in enumerate(route):
            if activity.start < previous_end:
                fail("activity_overlap", "Team activities overlap.", team_id)
            if index and activity.start > previous_end:
                fail(
                    "missing_waiting",
                    "Time between activities must be recorded as waiting.",
                    team_id,
                )
            if activity.from_site_id != location:
                fail(
                    "location_discontinuity",
                    "Resources cannot move between sites without travel.",
                    team_id,
                )
            location, previous_end = activity.to_site_id, activity.end
        if snapshot.return_to_start and location != snapshot.home_of(teams[team_id]):
            # A required-end rule explicitly replaces the default terminal site.
            if not any(r.kind == "required_end" and r.team_id == team_id for r in snapshot.rules):
                fail("terminal_location", "The plan omits the required return movement.", team_id)

    for team_id, member_team in teams.items():
        route = sorted(by_team.get(team_id, []), key=lambda a: (a.start, a.end))
        if snapshot.driving_rules is not None:
            for code, message in driving_findings(snapshot.driving_rules, route):
                fail(code, message, team_id)
        if not snapshot.rest_at_home:
            continue
        home = snapshot.home_of(member_team)
        for resource_id in member_team.resource_ids:
            for window in resources[resource_id].unavailable:
                covering = next((a for a in route if a.start <= window.start < a.end), None)
                before = [a for a in route if a.end <= window.start]
                rest_site: str | None
                if covering is not None:
                    rest_site = covering.from_site_id if covering.kind == "rest" else None
                else:
                    rest_site = before[-1].to_site_id if before else home
                if rest_site != home:
                    fail(
                        "rest_away_from_home",
                        "A calendar exception must be spent at the home depot.",
                        resource_id,
                    )

    for resource_id, activities in by_resource.items():
        route = sorted(activities, key=lambda a: (a.start, a.end))
        if len({a.team_id for a in route}) > 1:
            fail(
                "team_change_unsupported",
                "A fixed-team resource cannot switch teams within a scenario.",
                resource_id,
            )
        for previous, current in pairwise(route):
            if overlaps(previous.start, previous.end, current.start, current.end):
                fail(
                    "resource_overlap",
                    "A tractor, trailer or driver is double-booked.",
                    resource_id,
                )

    for team_id in teams:
        protected = sorted(
            (a for a in plan.assignments if a.team_id == team_id), key=lambda a: a.pickup_at
        )
        for previous_job, current_job in pairwise(protected):
            if overlaps(
                previous_job.pickup_at,
                previous_job.released_at,
                current_job.pickup_at,
                current_job.released_at,
            ):
                fail(
                    "ftl_job_overlap",
                    "A fixed full-truckload team cannot begin another job before unloading and turnaround finish.",
                    previous_job.job_id,
                    current_job.job_id,
                    team_id,
                )

    for assignment in plan.assignments:
        job = jobs.get(assignment.job_id)
        team = teams.get(assignment.team_id)
        if job is None or team is None:
            fail(
                "invalid_assignment",
                "Assignment references unknown entities.",
                assignment.job_id,
                assignment.team_id,
            )
            continue
        trailer = resources[team.trailer_id]
        if (
            trailer.equipment != job.equipment
            or trailer.capacity_kg is None
            or trailer.capacity_kg < job.weight_kg
        ):
            fail(
                "equipment_capacity",
                "Trailer equipment or capacity does not satisfy the job.",
                job.id,
                team.id,
            )
        activities = by_job[job.id]
        parts = {
            kind: [a for a in activities if a.kind == kind]
            for kind in ("loading", "loaded", "unloading", "turnaround")
        }
        if any(len(items) != 1 for items in parts.values()):
            fail(
                "missing_job_activity",
                "Job needs exactly one loading, loaded movement, unloading and turnaround.",
                job.id,
            )
            continue
        loading, loaded, unloading, turnaround = (parts[k][0] for k in parts)
        if any(
            a.kind == "empty" and overlaps(a.start, a.end, loading.start, unloading.end)
            for a in by_team[team.id]
        ):
            fail(
                "empty_while_loaded",
                "Movement cannot be empty while the trailer still carries an undelivered job.",
                job.id,
                team.id,
            )
        if any(a.team_id != team.id for a in activities):
            fail("assignment_team", "Job activities use a different team.", job.id)
        if (
            loading.from_site_id != job.pickup_site_id
            or loaded.from_site_id != job.pickup_site_id
            or loaded.to_site_id != job.delivery_site_id
            or unloading.from_site_id != job.delivery_site_id
            or turnaround.from_site_id != job.delivery_site_id
        ):
            fail(
                "job_location", "Job activity locations disagree with pickup and delivery.", job.id
            )
        if (
            loading.end != loaded.start
            or loaded.end > unloading.start
            or unloading.end != turnaround.start
        ):
            fail(
                "job_sequence",
                "Pickup, travel, delivery and turnaround are not continuous.",
                job.id,
            )
        if (
            loading.end - loading.start != timedelta(minutes=job.loading_minutes)
            or unloading.end - unloading.start != timedelta(minutes=job.unloading_minutes)
            or turnaround.end - turnaround.start != timedelta(minutes=job.turnaround_minutes)
        ):
            fail("service_duration", "Service or turnaround duration is incorrect.", job.id)
        delivery_time = (
            unloading.start if job.delivery_window_kind == "service_start" else unloading.end
        )
        if (
            not job.pickup_window.start <= loading.start <= job.pickup_window.end
            or not job.delivery_window.start <= delivery_time <= job.delivery_window.end
        ):
            fail("time_window", "Pickup or delivery violates its original time window.", job.id)
        if loading.start >= snapshot.horizon.end:
            fail(
                "outside_horizon", "A reconsidered job starts beyond the decision horizon.", job.id
            )
        if (assignment.pickup_at, assignment.delivery_at, assignment.released_at) != (
            loading.start,
            delivery_time,
            turnaround.end,
        ):
            fail(
                "assignment_times", "Assignment summary differs from its actual activities.", job.id
            )
        for lock in snapshot.locks:
            if lock.job_id == job.id and (
                lock.team_id != team.id
                or (lock.pickup_at is not None and lock.pickup_at != loading.start)
            ):
                fail("lock_violation", "A protected assignment was changed.", job.id)

    for lock in snapshot.locks:
        if lock.job_id not in actual:
            fail("lock_violation", "A protected assignment cannot be dropped.", lock.job_id)

    penalty = 0
    for rule in snapshot.rules:
        if rule.kind == "resource_unavailable" and rule.window:
            for activity in by_resource.get(rule.resource_id or "", []):
                if any(
                    overlaps(start, end, rule.window.start, rule.window.end)
                    for start, end in work_intervals(activity)
                ):
                    fail("rule_unavailable", "Activity violates approved unavailability.", rule.id)
        elif rule.kind == "required_end" and rule.window:
            team = teams[rule.team_id or ""]
            route = sorted(by_team.get(team.id, []), key=lambda a: (a.start, a.end))
            location = route[-1].to_site_id if route else resources[team.tractor_id].site_id
            end = (
                route[-1].end
                if route
                else max(
                    snapshot.horizon.start,
                    *(resources[r].availability.start for r in team.resource_ids),
                )
            )
            if location != rule.site_id or end > rule.window.end:
                fail(
                    "required_end",
                    "Team must finish at the required site before the deadline.",
                    rule.id,
                )
        elif rule.kind == "customer_eligibility":
            for assignment in plan.assignments:
                if (
                    assignment.team_id == rule.team_id
                    and jobs.get(assignment.job_id)
                    and jobs[assignment.job_id].customer != rule.customer
                ):
                    fail(
                        "customer_eligibility",
                        "Team is restricted to the approved customer.",
                        rule.id,
                        assignment.job_id,
                    )
        elif rule.kind == "preferred_assignment":
            matched = next((a for a in plan.assignments if a.job_id == rule.job_id), None)
            if matched and matched.team_id != rule.team_id:
                if rule.strength == "hard":
                    fail(
                        "required_assignment",
                        "Required team assignment was not respected.",
                        rule.id,
                    )
                else:
                    penalty += rule.penalty_minor

    # Findings are stable and concise even if one bad route causes repeated violations.
    unique = {(f.code, f.message, f.entity_ids): f for f in findings}
    prices = [jobs[a.job_id].revenue_minor for a in plan.assignments if a.job_id in jobs]
    costs = calculate_cost(plan.activities, snapshot.costs).model_copy(
        update={"revenue_minor": None if None in prices else sum(p or 0 for p in prices)}
    )
    return plan.model_copy(
        update={
            "findings": tuple(unique.values()),
            "costs": costs,
            "objective_penalty_minor": penalty,
        }
    )
