"""Plan a scenario from the command line.

uv run freight plan ../data/saudi/scenarios/pilot/snapshot.json
uv run freight plan ../data/saudi/scenarios/full/snapshot.json --seconds 60
uv run freight plan ../data/saudi/scenarios/pilot/snapshot.json --method baseline
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from freight.board import empty_breakdown, render_board
from freight.domain.models import Plan, Snapshot
from freight.fixtures import demo_snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.engine import plan_lns
from freight.planning.solver import solve_plan


def summary(snapshot: Snapshot, plan: Plan) -> str:
    confirmed = sum(job.state == "confirmed" for job in snapshot.jobs)
    offered = {job.id for job in snapshot.jobs if job.state == "offered"}
    accepted = [a for a in plan.assignments if a.job_id in offered]
    lines = [
        f"Scenario   {snapshot.name}",
        f"Method     {plan.method} | {plan.outcome} | {plan.runtime_ms / 1000:.1f} s",
        f"Valid      {'yes' if plan.valid else 'NO'}",
        f"Served     {len(plan.assignments) - len(accepted)}/{confirmed} confirmed jobs"
        + (f" + {len(accepted)}/{len(offered)} offered loads accepted" if offered else ""),
    ]
    if plan.unserved_job_ids:
        lines.append(f"Unserved   {', '.join(plan.unserved_job_ids)}")
    costs = plan.costs
    if costs:
        empty, loaded = costs.empty_distance_m / 1000, costs.loaded_distance_m / 1000
        share = empty / (empty + loaded) if empty + loaded else 0
        lines.append(f"Distance   {loaded:,.0f} km loaded | {empty:,.0f} km empty ({share:.0%})")
        reasons = empty_breakdown(plan)
        lines.append(
            "Empty km   " + " | ".join(f"{k} {v / 1000:,.0f}" for k, v in sorted(reasons.items()))
        )
        if costs.total_minor is not None:
            lines.append(f"Cost       SAR {costs.total_minor / 100:,.0f} (modeled)")
        if costs.revenue_minor is not None and costs.total_minor is not None:
            days = (snapshot.horizon.end - snapshot.horizon.start).total_seconds() / 86400
            per_truck_day = costs.revenue_minor / 100 / len(snapshot.teams) / days
            lines.append(
                f"Revenue    SAR {costs.revenue_minor / 100:,.0f} | contribution SAR "
                f"{(costs.revenue_minor - costs.total_minor) / 100:,.0f} | "
                f"SAR {per_truck_day:,.0f} per truck-day"
            )
    if plan.method == "lns" and plan.model_stats:
        stats = plan.model_stats
        lines.append(
            f"Search     {stats.get('iterations', 0)} iterations, "
            f"{stats.get('improved', 0)} improvements"
        )
    for code, count in Counter(f.code for f in plan.findings).most_common():
        lines.append(f"Finding    {code} x{count}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a freight scenario")
    parser.add_argument("command", choices=["plan"])
    parser.add_argument("scenario", type=Path, nargs="?", help="snapshot.json (default: demo)")
    parser.add_argument("--method", choices=["lns", "baseline", "cp_sat"], default="lns")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--diagnostic", action="store_true", help="Allow unserved jobs (CP-SAT only)"
    )
    parser.add_argument(
        "--confirmed-only", action="store_true", help="Ignore offered loads (for comparisons)"
    )
    parser.add_argument("--json", type=Path, help="Also write the full plan to this file")
    parser.add_argument("--board", type=Path, help="Also write an HTML plan board to this file")
    args = parser.parse_args()
    snapshot = (
        Snapshot.model_validate_json(args.scenario.read_text(encoding="utf-8"))
        if args.scenario
        else demo_snapshot()
    )
    if args.confirmed_only:
        snapshot = snapshot.model_copy(
            update={"jobs": tuple(j for j in snapshot.jobs if j.state == "confirmed")}
        )
    if args.method == "lns":
        plan = plan_lns(snapshot, seconds=args.seconds, seed=args.seed)
    elif args.method == "baseline":
        plan = baseline_plan(snapshot, seconds=args.seconds)
    else:
        plan = solve_plan(snapshot, seconds=args.seconds, diagnostic=args.diagnostic)
    print(summary(snapshot, plan))
    if args.board:
        args.board.write_text(render_board(snapshot, plan), encoding="utf-8")
        print(f"Board      {args.board.resolve()}")
    if args.json:
        args.json.write_text(
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
