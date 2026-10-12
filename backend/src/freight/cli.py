import argparse
import json
from pathlib import Path

from freight.domain.models import Snapshot
from freight.fixtures import benchmark_snapshot, demo_snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.solver import solve_plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditable synthetic freight planning")
    parser.add_argument("command", choices=["plan", "fixture", "benchmark"])
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--method", choices=["baseline", "cp_sat"], default="baseline")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    snapshot = (
        Snapshot.model_validate_json(args.fixture.read_text(encoding="utf-8"))
        if args.fixture
        else benchmark_snapshot()
        if args.command == "benchmark"
        else demo_snapshot()
    )
    if args.command == "fixture":
        print(snapshot.model_dump_json(indent=2))
        return
    plan = (
        baseline_plan(snapshot)
        if args.method == "baseline"
        else solve_plan(snapshot, seconds=args.seconds, diagnostic=args.diagnostic)
    )
    print(
        json.dumps(
            {
                "snapshot_hash": snapshot.fingerprint,
                "plan": plan.model_dump(mode="json"),
                "valid": plan.valid,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
