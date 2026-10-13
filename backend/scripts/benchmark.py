"""Fixed engine benchmark. Every engine change must be measured with it.

    uv run python scripts/benchmark.py           # full suite, about 10 minutes
    uv run python scripts/benchmark.py --quick   # short budgets for a smoke check

Three suites:
- exact: small Saudi scenarios where CP-SAT proves the optimum, so the engine's
  true gap is known exactly.
- pilot and full: the committed scenarios, several seeds. The gap there is an
  upper bound, measured against the min-cost-flow lower bound.

Results go to docs/benchmarks/<date>-<commit>.json and docs/benchmarks/README.md.
"""

import argparse
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from generate_saudi_scenario import scenario

from freight.domain.models import Plan, Snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.bounds import lower_bound
from freight.planning.engine import plan_lns
from freight.planning.solver import solve_plan

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "benchmarks"


def load(name: str) -> Snapshot:
    path = ROOT / "data" / "saudi" / "scenarios" / name / "snapshot.json"
    return Snapshot.model_validate_json(path.read_text(encoding="utf-8"))


def confirmed_only(snapshot: Snapshot) -> Snapshot:
    jobs = tuple(j for j in snapshot.jobs if j.state == "confirmed")
    return snapshot.model_copy(update={"jobs": jobs})


def measure(snapshot: Snapshot, plan: Plan, bound: bool = True) -> dict[str, Any]:
    offered = {j.id for j in snapshot.jobs if j.state == "offered"}
    served = {a.job_id for a in plan.assignments}
    costs = plan.costs
    cost = costs.total_minor if costs else None
    floor = lower_bound(snapshot, served) if bound and plan.valid else None
    empty = costs.empty_distance_m if costs else 0
    loaded = costs.loaded_distance_m if costs else 0
    days = (snapshot.horizon.end - snapshot.horizon.start).total_seconds() / 86400
    return {
        "method": plan.method,
        "valid": plan.valid,
        "seconds": round(plan.runtime_ms / 1000, 1),
        "confirmed": sum(j.state == "confirmed" for j in snapshot.jobs),
        "served": len(served - offered),
        "offers": f"{len(served & offered)}/{len(offered)}",
        "cost_sar": round(cost / 100) if cost is not None else None,
        "revenue_sar": round(costs.revenue_minor / 100) if costs and costs.revenue_minor else None,
        "contribution_sar": (
            round((costs.revenue_minor - cost) / 100)
            if costs and costs.revenue_minor is not None and cost is not None
            else None
        ),
        "revenue_per_truck_day": (
            round(costs.revenue_minor / 100 / len(snapshot.teams) / days)
            if costs and costs.revenue_minor
            else None
        ),
        "empty_share": round(empty / (empty + loaded), 3) if empty + loaded else None,
        "bound_sar": round(floor / 100) if floor is not None else None,
        "gap_vs_bound": round((cost - floor) / cost, 4) if floor is not None and cost else None,
        "iterations": plan.model_stats.get("iterations") if plan.method == "lns" else None,
    }


def exact_suite(cases: int, cp_seconds: float, lns_seconds: float) -> list[dict[str, Any]]:
    rows = []
    for seed in range(1, cases + 1):
        data = scenario(
            "--name", f"exact-{seed}", "--trucks", "6", "--days", "2", "--seed", str(seed),
            "--no-rest-blocks", "--loads-per-truck-day", "1.0", "--spot-share", "0",
        )  # fmt: skip
        generated = Snapshot.model_validate(data)
        # Keep only work that can be served together, so both solvers face the same
        # strict problem: CP-SAT finds the largest servable set, then proves the optimum.
        coverage = solve_plan(generated, seconds=cp_seconds, diagnostic=True)
        servable = {a.job_id for a in coverage.assignments}
        snapshot = generated.model_copy(
            update={"jobs": tuple(j for j in generated.jobs if j.id in servable)}
        )
        proven = solve_plan(snapshot, seconds=cp_seconds)
        engine = plan_lns(snapshot, seconds=lns_seconds, seed=1)
        row: dict[str, Any] = {
            "case": f"exact-{seed}",
            "jobs": len(snapshot.jobs),
            "generated_jobs": len(generated.jobs),
            "cp_sat": measure(snapshot, proven, bound=False) | {"outcome": proven.outcome},
            "engine": measure(snapshot, engine),
        }
        same = row["cp_sat"]["served"] == row["engine"]["served"] == len(snapshot.jobs)
        cp_cost, lns_cost = row["cp_sat"]["cost_sar"], row["engine"]["cost_sar"]
        row["exact_gap"] = (
            round((lns_cost - cp_cost) / cp_cost, 4)
            if proven.outcome == "optimal" and same and cp_cost
            else None
        )
        rows.append(row)
        print(
            f"exact-{seed}: {len(snapshot.jobs)} jobs | CP-SAT {proven.outcome} SAR {cp_cost} | "
            f"engine SAR {lns_cost} | gap {row['exact_gap']}",
            flush=True,
        )
    return rows


def scenario_suite(name: str, seconds: float, seeds: list[int]) -> dict[str, Any]:
    snapshot = load(name)
    result: dict[str, Any] = {"scenario": name, "runs": []}
    for seed in seeds:
        run = measure(snapshot, plan_lns(snapshot, seconds=seconds, seed=seed)) | {"seed": seed}
        result["runs"].append(run)
        print(f"{name} seed {seed}: {run}", flush=True)
    only = confirmed_only(snapshot)
    result["confirmed_only"] = measure(only, plan_lns(only, seconds=seconds, seed=seeds[0]))
    print(f"{name} confirmed only: {result['confirmed_only']}", flush=True)
    if name == "pilot":
        result["greedy"] = measure(only, baseline_plan(only, seconds=seconds))
        print(f"{name} greedy: {result['greedy']}", flush=True)
    return result


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Engine benchmark",
        "",
        f"Latest run: {report['date']} · commit `{report['commit']}` · {report['machine']} · "
        f"`scripts/benchmark.py{' --quick' if report['quick'] else ''}`. Raw results: "
        f"[{report['file']}]({report['file']}).",
        "",
        "**Exact gap**: engine cost vs CP-SAT's proven optimum on small scenarios (6 trucks, 48 h, "
        "classic rules; jobs that cannot all be served together are removed first, so both solve "
        "the identical problem). CP-SAT's model has no driving-hours rules, so this calibrates the "
        "search, not the realistic rules. **Gap vs bound**: an upper limit on how far a plan can be from optimal for "
        "the jobs it serves; the true gap is smaller.",
        "",
        "Reading the numbers: the bound ignores waiting, rests and trips home, so it is loose. "
        "On the small cases, where the optimum is known, compare the exact gap with the gap vs "
        "bound to see how loose it is. Treat large-scenario bound gaps as a ceiling, and compare "
        "engine versions by cost on the same seeds.",
        "",
        "## Small scenarios with a proven optimum",
        "",
        "| Case | Jobs | CP-SAT | Optimum (SAR) | Engine (SAR) | Exact gap | Gap vs bound |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["exact"]:
        gap = row["exact_gap"]
        lines.append(
            f"| {row['case']} | {row['jobs']} | {row['cp_sat']['outcome']} | "
            f"{row['cp_sat']['cost_sar']:,} | {row['engine']['cost_sar']:,} | "
            f"{'—' if gap is None else f'{gap:.2%}'} | {pct(row['engine']['gap_vs_bound'])} |"
        )
    lines += [
        "",
        "## Committed scenarios",
        "",
        "| Scenario | Run | Served | Offers | Empty | Cost (SAR) | Contribution (SAR) | "
        "Revenue/truck-day | Gap vs bound | Iterations |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for suite in report["scenarios"]:
        runs = [(f"seed {r['seed']}", r) for r in suite["runs"]]
        runs.append(("confirmed only", suite["confirmed_only"]))
        if "greedy" in suite:
            runs.append(("old greedy, confirmed only", suite["greedy"]))
        for label, r in runs:
            lines.append(
                f"| {suite['scenario']} | {label} | {r['served']}/{r['confirmed']} | {r['offers']} | "
                f"{pct(r['empty_share'])} | {num(r['cost_sar'])} | {num(r['contribution_sar'])} | "
                f"{num(r['revenue_per_truck_day'])} | {pct(r['gap_vs_bound'])} | "
                f"{num(r['iterations'])} |"
            )
    return "\n".join(lines) + "\n"


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def num(value: float | None) -> str:
    return "—" if value is None else f"{value:,}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    quick = args.quick
    started = perf_counter()
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    report: dict[str, Any] = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "commit": commit or "unknown",
        "machine": f"{platform.processor() or platform.machine()}, {os.cpu_count()} logical CPUs",
        "quick": quick,
        "exact": exact_suite(3 if quick else 5, 20 if quick else 60, 3 if quick else 10),
        "scenarios": [
            scenario_suite("pilot", 10 if quick else 30, [1] if quick else [1, 2, 3]),
            scenario_suite("full", 20 if quick else 60, [1] if quick else [1, 2]),
        ],
    }
    report["total_seconds"] = round(perf_counter() - started)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    name = f"{stamp}-{report['commit']}{'-quick' if quick else ''}.json"
    report["file"] = name
    (OUT / name).write_text(json.dumps(report, indent=1), encoding="utf-8")
    (OUT / "README.md").write_text(markdown(report), encoding="utf-8")
    print(f"Wrote {OUT / name} in {report['total_seconds']} s")


if __name__ == "__main__":
    main()
