"""Plan a scenario from the command line.

uv run freight plan ../data/saudi/scenarios/pilot/snapshot.json
uv run freight plan ../data/saudi/scenarios/full/snapshot.json --seconds 60
uv run freight plan ../data/saudi/scenarios/pilot/snapshot.json --method baseline
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from freight.board import empty_breakdown, render_board
from freight.demo import build_demo
from freight.domain.models import Plan, Snapshot
from freight.explain import narrate, template, what_if, why
from freight.fixtures import demo_snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.engine import plan_lns
from freight.planning.lookahead import plan_with_lookahead
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
    if snapshot.end_values and plan.model_stats.get("end_value") is not None:
        lines.append(
            f"Look-ahead SAR {int(plan.model_stats['end_value']) / 100:,.0f} credited for where "
            "trucks end (planning value, not cash)"
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
    # Arabic text must print on Windows consoles too (their default code page cannot).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Plan a freight scenario")
    parser.add_argument(
        "command",
        choices=["plan", "demo", "explain", "whatif"],
        help=(
            "plan: one plan | demo: a simulated week as a small website | "
            "explain: why a job is on its truck | whatif: re-plan under a change"
        ),
    )
    parser.add_argument("scenario", type=Path, nargs="?", help="snapshot.json (default: demo)")
    parser.add_argument("--method", choices=["lns", "baseline", "cp_sat"], default="lns")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--rounds",
        type=int,
        help="Stop after this many search rounds instead of --seconds (repeatable results)",
    )
    parser.add_argument(
        "--diagnostic", action="store_true", help="Allow unserved jobs (CP-SAT only)"
    )
    parser.add_argument(
        "--confirmed-only", action="store_true", help="Ignore offered loads (for comparisons)"
    )
    parser.add_argument(
        "--lookahead",
        action="store_true",
        help="Value where trucks end the plan using a model of the following days",
    )
    parser.add_argument("--json", type=Path, help="Also write the full plan to this file")
    parser.add_argument("--board", type=Path, help="Also write an HTML plan board to this file")
    parser.add_argument("--out", type=Path, default=Path("demo"), help="demo: output folder")
    parser.add_argument("--days", type=int, default=7, help="demo: mornings to simulate")
    parser.add_argument("--freeze", type=float, default=6, help="demo: freeze window in hours")
    parser.add_argument(
        "--penalty", type=int, default=300, help="demo: SAR penalty for moving a job"
    )
    parser.add_argument("--job", help="explain/whatif: job reference, e.g. SA-26053")
    parser.add_argument("--drop", help="whatif: cancel this job reference")
    parser.add_argument("--unavailable", help="whatif: this team (e.g. team-DMM-007) is down")
    parser.add_argument("--from", dest="start", help="whatif: start, e.g. 2026-10-18T12:00+03:00")
    parser.add_argument("--to", dest="end", help="whatif: end, e.g. 2026-10-18T20:00+03:00")
    parser.add_argument("--assign", help="whatif: force this job reference onto --team")
    parser.add_argument("--team", help="whatif: team id for --assign")
    parser.add_argument("--lang", choices=["en", "ar"], default="en", help="explanation language")
    parser.add_argument(
        "--no-ai", action="store_true", help="explain with the built-in template only"
    )
    args = parser.parse_args()
    snapshot = (
        Snapshot.model_validate_json(args.scenario.read_text(encoding="utf-8"))
        if args.scenario
        else demo_snapshot()
    )
    if args.command == "demo":
        data = build_demo(
            snapshot,
            args.out,
            days=args.days,
            seconds=args.seconds,
            seed=args.seed,
            freeze_hours=args.freeze,
            change_penalty_minor=args.penalty * 100,
            rounds=args.rounds,
        )
        result = data["result"]
        assert isinstance(result, dict)
        print(
            f"Week       {result['served']}/{result['confirmed']} contract jobs, "
            f"{result['offers']} offers, contribution SAR {result['contribution_sar']:,}, "
            f"{result['changed_within_a_day']} changes after drivers were told, "
            f"{result['valid_days']}/{args.days} valid mornings"
        )
        print(f"Demo       {(args.out / 'index.html').resolve()}")
        return
    if args.command in ("explain", "whatif"):
        explain_or_what_if(snapshot, args)
        return
    if args.confirmed_only:
        snapshot = snapshot.model_copy(
            update={"jobs": tuple(j for j in snapshot.jobs if j.state == "confirmed")}
        )
    if args.method == "lns" and args.lookahead:
        snapshot, plan = plan_with_lookahead(snapshot, seconds=args.seconds, seed=args.seed)
    elif args.method == "lns":
        plan = plan_lns(snapshot, seconds=args.seconds, seed=args.seed, rounds=args.rounds)
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


def explain_or_what_if(snapshot: Snapshot, args: argparse.Namespace) -> None:
    by_reference = {j.reference: j.id for j in snapshot.jobs}
    plan = plan_lns(snapshot, seconds=args.seconds, seed=args.seed, rounds=args.rounds or 3000)
    if args.command == "explain":
        if args.job not in by_reference:
            raise SystemExit("Give --job with a job reference from the scenario, e.g. SA-26053")
        facts = why(snapshot, plan, by_reference[args.job])
    else:
        if args.drop:
            change: dict[str, object] = {"kind": "drop", "job": by_reference[args.drop]}
        elif args.unavailable:
            change = {
                "kind": "unavailable",
                "team": args.unavailable,
                "start": datetime.fromisoformat(args.start),
                "end": datetime.fromisoformat(args.end),
            }
        elif args.assign:
            change = {"kind": "assign", "job": by_reference[args.assign], "team": args.team}
        else:
            raise SystemExit("Give one of --drop, --unavailable (with --from/--to), --assign")
        facts, _, _ = what_if(snapshot, plan, change, seed=args.seed)
    text, source = (
        (template(facts, args.lang), "template") if args.no_ai else narrate(facts, args.lang)
    )
    print(json.dumps(facts, ensure_ascii=False, indent=1))
    print(f"\n[{source}]\n{text}")


if __name__ == "__main__":
    main()
