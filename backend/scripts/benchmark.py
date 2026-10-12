"""Measured synthetic benchmark; never substitutes a heuristic result for CP-SAT."""

import json
import os
import platform
from pathlib import Path
from time import perf_counter

from freight.fixtures import benchmark_snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.solver import solve_plan
from freight.validation import validate_plan

snapshot = benchmark_snapshot()
report = {
    "fixture": snapshot.name,
    "snapshot_hash": snapshot.fingerprint,
    "platform": platform.platform(),
    "processor": platform.processor(),
    "logical_cpus": os.cpu_count(),
    "solver_threads": 1,
    "solver_seed": 7,
    "decision_horizon_hours": 48,
    "lane_source": "Synthetic fixture only",
    "results": {},
}
baseline = None
for method in ("baseline", "cp_sat"):
    started = perf_counter()
    plan = (
        baseline_plan(snapshot, seconds=30)
        if method == "baseline"
        else solve_plan(snapshot, seconds=30, hint=baseline)
    )
    if method == "baseline":
        baseline = plan
    elapsed = perf_counter() - started
    validating = perf_counter()
    checked = validate_plan(snapshot, plan)
    validation_ms = (perf_counter() - validating) * 1000
    report["results"][method] = {
        "outcome": plan.outcome,
        "valid": checked.valid,
        "coverage": plan.coverage,
        "served": len(plan.assignments),
        "total_jobs": len(snapshot.jobs),
        "wall_seconds": round(elapsed, 3),
        "validation_ms": round(validation_ms, 3),
        "modeled_cost_minor": plan.costs.total_minor if plan.valid and plan.costs else None,
        "findings": [f.model_dump() for f in plan.findings],
        "solver_version": plan.solver_version,
    }
    report["results"][method]["model_stats"] = plan.model_stats
    print(method, report["results"][method], flush=True)
target = Path(__file__).resolve().parents[2] / "docs" / "benchmark.json"
target.write_text(json.dumps(report, indent=2), encoding="utf-8")
