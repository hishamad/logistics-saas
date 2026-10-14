"""Daily rolling re-planning over the full week: which policy works best?

    uv run python scripts/daily.py                 # about 8 minutes on 8 cores
    uv run python scripts/daily.py --seconds 10 --seeds 1 2

Each morning plans 48 h with the jobs known by then (orders arrive 12-72 h ahead,
spot offers 6-36 h ahead), starting where the trucks really are, and executes
the day. Policies:
- free:         re-plan from scratch every morning (no freeze, no change penalty)
- penalty only: SAR 300 penalty for moving a job to another truck, no freeze
- freeze 6 h:   6 h freeze + the penalty
- calm:         12 h freeze + the penalty
- lookahead: calm + look-ahead values for where trucks end each 48 h plan
Every run is repeated with several search seeds; results are mean ± sd.
"""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from freight.domain.models import Plan, Snapshot
from freight.planning.daily import myopic, simulate
from freight.planning.lookahead import plan_with_lookahead

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "benchmarks"
POLICIES = {
    "free": {"freeze_hours": 0, "change_penalty_minor": 0, "lookahead": False},
    "penalty only": {"freeze_hours": 0, "change_penalty_minor": 30_000, "lookahead": False},
    "freeze 6 h": {"freeze_hours": 6, "change_penalty_minor": 30_000, "lookahead": False},
    "calm": {"freeze_hours": 12, "change_penalty_minor": 30_000, "lookahead": False},
    "lookahead": {"freeze_hours": 12, "change_penalty_minor": 30_000, "lookahead": True},
}


def with_lookahead(snapshot: Snapshot, seconds: float, seed: int) -> tuple[Snapshot, Plan]:
    return plan_with_lookahead(snapshot, seconds=seconds, seed=seed)


def run(policy: str, seed: int, seconds: float) -> tuple[str, int, dict[str, Any]]:
    path = ROOT / "data" / "saudi" / "scenarios" / "full" / "snapshot.json"
    base = Snapshot.model_validate_json(path.read_text(encoding="utf-8"))
    settings = POLICIES[policy]
    result = simulate(
        base,
        planner=with_lookahead if settings["lookahead"] else myopic,
        freeze_hours=float(settings["freeze_hours"]),
        change_penalty_minor=int(settings["change_penalty_minor"]),
        seconds=seconds,
        seed=seed,
    )
    return policy, seed, result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    jobs = [(p, s) for p in POLICIES for s in args.seeds]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        runs = list(pool.map(run, *zip(*jobs, strict=True), [args.seconds] * len(jobs)))
    metrics = [
        ("valid_days", "Valid days"),
        ("served", "Confirmed served"),
        ("offers", "Offers executed"),
        ("contribution_sar", "Contribution (SAR)"),
        ("empty_km", "Empty km"),
        ("changed_within_a_day", "Changed after drivers were told"),
    ]
    summary: dict[str, dict[str, tuple[float, float]]] = {}
    for policy in POLICIES:
        rows = [r for p, _, r in runs if p == policy]
        summary[policy] = {
            key: (mean(float(r[key]) for r in rows), stdev(float(r[key]) for r in rows))
            for key, _ in metrics
        }
    lines = [
        "# Daily rolling re-planning: policy comparison",
        "",
        f"`scripts/daily.py --seconds {args.seconds:g}`: the full scenario (100 trucks, 7 days), "
        "planned every morning for 48 h with only the jobs known by then, then executed for one "
        f"day. Mean ± sd over search seeds {args.seeds}. Contribution counts executed work only.",
        "",
        "| Policy | " + " | ".join(label for _, label in metrics) + " |",
        "| --- | " + " | ".join("---" for _ in metrics) + " |",
    ]
    for policy, values in summary.items():
        cells = [f"{m:,.0f} ± {s:,.0f}" for m, s in (values[key] for key, _ in metrics)]
        lines.append(f"| {policy} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "Simplifications: plans are executed exactly (no breakdowns or delays), and drivers "
        "start each morning's plan rested (driving hours are not carried across days).",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "daily.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "daily.json").write_text(
        json.dumps([{"policy": p, "seed": s, **r} for p, s, r in runs], indent=1), encoding="utf-8"
    )
    print("\n".join(lines))


if __name__ == "__main__":
    main()
