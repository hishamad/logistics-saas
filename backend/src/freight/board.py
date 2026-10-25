"""Render a plan as a self-contained HTML plan board (no server, no internet).

One row per truck shows its week on a shared timeline; hovering explains an
activity and clicking a truck opens its itinerary. All figures come from the
validated plan; the page only formats them.
"""

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from freight.domain.models import Activity, Plan, Snapshot
from freight.planning.diff import PlanDiff

TEMPLATE = Path(__file__).with_name("board_template.html")
KINDS = {
    "loaded": 0,
    "empty": 1,
    "loading": 2,
    "unloading": 2,
    "turnaround": 2,
    "waiting": 3,
    "rest": 4,
}


def empty_breakdown(plan: Plan) -> Counter[str]:
    """Empty metres by reason: before the first job, between jobs, after the last."""
    by_team: defaultdict[str, list[Activity]] = defaultdict(list)
    for activity in plan.activities:
        by_team[activity.team_id].append(activity)
    reasons: Counter[str] = Counter()
    for activities in by_team.values():
        activities.sort(key=lambda a: a.start)
        seen = 0
        total = len({a.job_id for a in activities if a.job_id})
        for activity in activities:
            if activity.kind == "loading":
                seen += 1
            if activity.kind == "empty":
                reason = (
                    "To first pickup"
                    if seen == 0
                    else "After last job"
                    if seen == total
                    else "Between jobs"
                )
                reasons[reason] += activity.distance_m
    return reasons


def board_data(
    snapshot: Snapshot,
    plan: Plan,
    changes: PlanDiff | None = None,
    nav: dict[str, str] | None = None,
) -> dict[str, object]:
    """Everything the page shows. ``changes`` adds a "since yesterday" panel; ``nav`` links."""
    origin = snapshot.horizon.start

    def minute(value: datetime) -> int:
        return round((value - origin).total_seconds() / 60)

    resources = {r.id: r for r in snapshot.resources}
    sites = {s.id: [s.name, s.name_ar] for s in snapshot.sites}
    jobs: dict[str, dict[str, object]] = {
        j.id: {
            "ref": j.reference,
            "customer": j.customer,
            "from": j.pickup_site_id,
            "to": j.delivery_site_id,
            "offer": j.state == "offered",
            "revenue": j.revenue_minor,
            "tonnes": j.weight_kg / 1000,
            "equipment": j.equipment,
        }
        for j in snapshot.jobs
    }
    prices = {j.id: j.revenue_minor for j in snapshot.jobs}
    offers = {j.id for j in snapshot.jobs if j.state == "offered"}
    by_team: defaultdict[str, list[Activity]] = defaultdict(list)
    for activity in plan.activities:
        by_team[activity.team_id].append(activity)
    assigned = {a.job_id for a in plan.assignments}
    # When each resource cannot work: its calendar (weekly rest, leave) and the
    # dispatcher's rules (a truck in the workshop).
    blocked: defaultdict[str, list[tuple[datetime, datetime, str]]] = defaultdict(list)
    for resource in snapshot.resources:
        for window in resource.unavailable:
            blocked[resource.id].append((window.start, window.end, "calendar"))
    for rule in snapshot.rules:
        if rule.kind == "resource_unavailable" and rule.window:
            blocked[rule.resource_id or ""].append((rule.window.start, rule.window.end, "rule"))
    teams = []
    for team in snapshot.teams:
        activities = sorted(by_team.get(team.id, []), key=lambda a: a.start)
        team_jobs = {a.job_id for a in activities if a.job_id}
        driving = sum(
            (a.end - a.start).total_seconds() - a.paused_seconds
            for a in activities
            if a.kind in ("loaded", "empty")
        )
        depot = snapshot.home_of(team)
        teams.append(
            {
                "id": team.id,
                "name": team.name,
                "depot": depot,
                "equipment": resources[team.trailer_id].equipment,
                "acts": [
                    [
                        KINDS[a.kind],
                        minute(a.start),
                        minute(a.end),
                        a.job_id,
                        a.from_site_id,
                        a.to_site_id,
                        round(a.distance_m / 1000),
                        [[p.kind, minute(p.start), minute(p.end)] for p in a.pauses],
                        a.kind,
                    ]
                    for a in activities
                ],
                "blocks": sorted(
                    {
                        (max(0, minute(start)), minute(end), source)
                        for resource_id in team.resource_ids
                        for start, end, source in blocked[resource_id]
                        if end > origin and start < snapshot.horizon.end
                    }
                ),
                "stats": {
                    "jobs": len(team_jobs),
                    "offers": len(team_jobs & offers),
                    "loaded_km": round(
                        sum(a.distance_m for a in activities if a.kind == "loaded") / 1000
                    ),
                    "empty_km": round(
                        sum(a.distance_m for a in activities if a.kind == "empty") / 1000
                    ),
                    "revenue": sum(prices.get(j) or 0 for j in team_jobs),
                    "driving_h": round(driving / 3600, 1),
                },
            }
        )
    costs = plan.costs
    days = (snapshot.horizon.end - origin).total_seconds() / 86400
    end = max([minute(snapshot.horizon.end), *(minute(a.end) for a in plan.activities)])
    confirmed = [j for j in snapshot.jobs if j.state == "confirmed"]
    offered = [j for j in snapshot.jobs if j.state == "offered"]
    return {
        "name": snapshot.name,
        "method": plan.method,
        "valid": plan.valid,
        "findings": sorted({f.code for f in plan.findings}),
        "released": [
            job_id
            for note in plan.notes
            if note.code == "lock_released"
            for job_id in note.entity_ids
        ],
        "origin": origin.isoformat(),
        "horizonEnd": minute(snapshot.horizon.end),
        "end": end,
        "sites": sites,
        "jobs": jobs,
        "teams": teams,
        "unserved": list(plan.unserved_job_ids),
        "kpis": {
            "confirmed": len(confirmed),
            "served": sum(1 for j in confirmed if j.id in assigned),
            "offered": len(offered),
            "accepted": sum(1 for j in offered if j.id in assigned),
            "loaded_km": round(costs.loaded_distance_m / 1000) if costs else 0,
            "empty_km": round(costs.empty_distance_m / 1000) if costs else 0,
            "cost": costs.total_minor if costs else None,
            "revenue": costs.revenue_minor if costs else None,
            "trucks": len(snapshot.teams),
            "days": days,
            "runtime_s": round(plan.runtime_ms / 1000, 1),
        },
        "emptyReasons": {k: round(v / 1000) for k, v in empty_breakdown(plan).items()},
        "frozen": sorted(lock.job_id for lock in snapshot.locks),
        "changes": describe_changes(snapshot, changes) if changes else None,
        "nav": nav,
    }


def describe_changes(snapshot: Snapshot, changes: PlanDiff) -> dict[str, object]:
    names = {t.id: t.name for t in snapshot.teams}
    refs = {j.id: j.reference for j in snapshot.jobs}
    open_jobs = set(refs)
    return {
        "moved": [[refs.get(j, j), names.get(a, a), names.get(b, b)] for j, a, b in changes.moved],
        "retimed": [
            [refs.get(j, j), names.get(t, t), x.isoformat(), y.isoformat()]
            for j, t, x, y in changes.retimed
        ],
        # Work done yesterday is not a change; only still-open jobs that lost their truck are.
        "dropped": [
            [refs.get(j, j), names.get(t, t)] for j, t in changes.dropped if j in open_jobs
        ],
        "added": len(changes.added),
        "unchanged": changes.unchanged,
        "notify": sorted(
            {t for _, a, b in changes.moved for t in (a, b)}
            | {t for _, t, _, _ in changes.retimed}
            | {t for j, t in changes.dropped if j in open_jobs}
        ),
    }


def render_board(
    snapshot: Snapshot,
    plan: Plan,
    changes: PlanDiff | None = None,
    nav: dict[str, str] | None = None,
) -> str:
    data = board_data(snapshot, plan, changes, nav)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Keep the embedded JSON from ever closing the script element.
    payload = payload.replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
