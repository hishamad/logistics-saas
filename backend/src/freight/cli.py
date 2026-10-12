"""Plan a scenario from the command line.

uv run freight plan ../data/saudi/scenarios/pilot/snapshot.json
uv run freight plan ../data/saudi/scenarios/pilot/snapshot.json --method cp_sat --seconds 60
"""

import argparse
import json
from pathlib import Path

from freight.domain.models import Plan, Snapshot
from freight.fixtures import demo_snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.solver import solve_plan


def summary(snapshot: Snapshot, plan: Plan) -> str:
    confirmed = sum(job.state == "confirmed" for job in snapshot.jobs)
    lines = [
        f"Scenario   {snapshot.name}",
        f"Method     {plan.method} | {plan.outcome} | {plan.runtime_ms / 1000:.1f} s",
        f"Valid      {'yes' if plan.valid else 'NO'}",
        f"Served     {len(plan.assignments)}/{confirmed} confirmed jobs",
    ]
    if plan.unserved_job_ids:
        lines.append(f"Unserved   {', '.join(plan.unserved_job_ids)}")
    if plan.costs:
        empty, loaded = plan.costs.empty_distance_m / 1000, plan.costs.loaded_distance_m / 1000
        share = empty / (empty + loaded) if empty + loaded else 0
        lines.append(f"Distance   {loaded:,.0f} km loaded | {empty:,.0f} km empty ({share:.0%})")
        if plan.costs.total_minor is not None:
            lines.append(f"Cost       SAR {plan.costs.total_minor / 100:,.0f} (modeled)")
    lines += [f"Finding    {f.code}: {f.message}" for f in plan.findings]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a freight scenario")
    parser.add_argument("command", choices=["plan"])
    parser.add_argument("scenario", type=Path, nargs="?", help="snapshot.json (default: demo)")
    parser.add_argument("--method", choices=["baseline", "cp_sat"], default="baseline")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument(
        "--diagnostic", action="store_true", help="Allow unserved jobs (CP-SAT only)"
    )
    parser.add_argument("--json", type=Path, help="Also write the full plan to this file")
    args = parser.parse_args()
    snapshot = (
        Snapshot.model_validate_json(args.scenario.read_text(encoding="utf-8"))
        if args.scenario
        else demo_snapshot()
    )
    plan = (
        baseline_plan(snapshot, seconds=args.seconds)
        if args.method == "baseline"
        else solve_plan(snapshot, seconds=args.seconds, diagnostic=args.diagnostic)
    )
    print(summary(snapshot, plan))
    if args.json:
        args.json.write_text(
            json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
