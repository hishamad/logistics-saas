"""Does look-ahead pay? A two-week rolling test.

    uv run python scripts/rolling.py            # about 3 minutes on 8 cores
    uv run python scripts/rolling.py --seconds 20 --search-seeds 1 2

Week 1 is the committed full scenario, planned twice: myopically, and with
look-ahead. Week 2 has new jobs (different generator seeds) and starts from
wherever each week-1 plan left the trucks: same trucks, trailers and home depots,
current location = week-1 end position, available once week-1 work is done.
Week 2 is always planned myopically, so the only difference is how week 1
positioned the fleet. The score is the two-week total contribution.
"""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from pathlib import Path
from statistics import mean, stdev
from typing import Any

from generate_saudi_scenario import scenario

from freight.domain.models import Plan, Snapshot, Window
from freight.planning.engine import Engine, plan_lns
from freight.planning.lookahead import plan_with_lookahead

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "benchmarks"


def week_one() -> Snapshot:
    path = ROOT / "data" / "saudi" / "scenarios" / "full" / "snapshot.json"
    return Snapshot.model_validate_json(path.read_text(encoding="utf-8"))


def week_two(first: Snapshot, plan: Plan, seed: int) -> Snapshot:
    """New jobs; the same fleet, relocated to where ``plan`` left each team."""
    fresh = Snapshot.model_validate(
        scenario(
            "--name",
            "week2",
            "--trucks",
            str(len(first.teams)),
            "--days",
            "7",
            "--seed",
            str(seed),
            "--realistic",
        )  # fmt: skip
    )
    horizon_end = first.horizon.end
    finish: dict[str, tuple[object, str]] = {}
    for a in plan.activities:
        if a.team_id not in finish or a.end > finish[a.team_id][0]:  # type: ignore[operator]
            finish[a.team_id] = (a.end, a.to_site_id)
    resources = {r.id: r for r in first.resources}
    engine = Engine(first)
    moved, teams = [], []
    for team in first.teams:
        home = first.home_of(team)
        end_time, site = finish.get(team.id, (horizon_end, home))
        delay = max(timedelta(0), end_time - horizon_end)  # type: ignore[operator]
        ready = fresh.horizon.start + delay
        # A dispatcher schedules a day off when the driver can actually be home for it.
        home_by = ready + timedelta(minutes=engine.elapsed(engine.lane(site, home)[0]) + 60)
        for rid in team.resource_ids:
            r = resources[rid]
            available = r.availability.model_copy(update={"start": ready})
            days_off = tuple(
                w if w.start >= home_by else Window(start=home_by, end=home_by + (w.end - w.start))
                for w in r.unavailable
            )
            moved.append(
                r.model_copy(
                    update={"site_id": site, "availability": available, "unavailable": days_off}
                )
            )
        teams.append(team.model_copy(update={"home_site_id": home}))
    return fresh.model_copy(update={"resources": tuple(moved), "teams": tuple(teams)})


def summary(snapshot: Snapshot, plan: Plan) -> dict[str, Any]:
    offered = {j.id for j in snapshot.jobs if j.state == "offered"}
    served = {a.job_id for a in plan.assignments}
    c = plan.costs
    assert c is not None and c.total_minor is not None and c.revenue_minor is not None
    return {
        "valid": plan.valid,
        "served": len(served - offered),
        "confirmed": sum(j.state == "confirmed" for j in snapshot.jobs),
        "offers": len(served & offered),
        "contribution_sar": round((c.revenue_minor - c.total_minor) / 100),
        "empty_km": round(c.empty_distance_m / 1000),
    }


def plan_week_one(policy: str, seconds: float) -> tuple[str, dict[str, Any], str]:
    first = week_one()
    if policy == "lookahead":
        first, plan = plan_with_lookahead(first, seconds=seconds, seed=1)
    else:
        plan = plan_lns(first, seconds=seconds, seed=1)
    return policy, summary(first, plan), plan.model_dump_json()


def plan_week_two(policy: str, plan_json: str, demand: int, seed: int, seconds: float) -> int:
    plan = Plan.model_validate_json(plan_json)
    second = week_two(week_one(), plan, demand)
    result = summary(second, plan_lns(second, seconds=seconds, seed=seed))
    assert result["valid"], f"week 2 plan invalid ({policy}, demand {demand}, seed {seed})"
    return int(result["contribution_sar"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--demand-seeds", type=int, nargs="+", default=[43, 44])
    parser.add_argument("--search-seeds", type=int, nargs="+", default=[1, 2, 3, 4])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        firsts = list(pool.map(plan_week_one, ["myopic", "lookahead"], [args.seconds] * 2))
        runs = [
            (policy, plan_json, demand, seed)
            for policy, _, plan_json in firsts
            for demand in args.demand_seeds
            for seed in args.search_seeds
        ]
        seconds = [args.seconds] * len(runs)
        contributions = list(pool.map(plan_week_two, *zip(*runs, strict=True), seconds))
    results: dict[str, Any] = {}
    for policy, week1, _ in firsts:
        week2 = [c for (p, *_), c in zip(runs, contributions, strict=True) if p == policy]
        results[policy] = {
            "week1": week1,
            "week2_mean": round(mean(week2)),
            "week2_sd": round(stdev(week2)),
            "week2_runs": week2,
        }
    gap = results["lookahead"]["week2_mean"] - results["myopic"]["week2_mean"]
    error = (
        results["lookahead"]["week2_sd"] ** 2 / len(week2)
        + results["myopic"]["week2_sd"] ** 2 / len(week2)
    ) ** 0.5
    lines = [
        "# Look-ahead: two-week rolling test",
        "",
        f"`scripts/rolling.py --seconds {args.seconds:g}`. Week 1 is the full scenario, planned "
        "myopically or with look-ahead. Week 2 has new jobs (demand seeds "
        f"{args.demand_seeds}) and starts from wherever week 1 left each truck. It is planned "
        f"myopically {len(args.search_seeds)} times per demand seed with different search seeds, "
        "because a single run is too noisy to compare.",
        "",
        "| Policy | Week 1 contribution | Week 1 confirmed served | Week 2 contribution, mean ± sd "
        "| Two-week total |",
        "| --- | --- | --- | --- | --- |",
    ]
    for policy, r in results.items():
        w1 = r["week1"]
        lines.append(
            f"| {policy} | {w1['contribution_sar']:,} | {w1['served']}/{w1['confirmed']} | "
            f"{r['week2_mean']:,} ± {r['week2_sd']:,} (n={len(r['week2_runs'])}) | "
            f"**{w1['contribution_sar'] + r['week2_mean']:,}** |"
        )
    lines += [
        "",
        f"Week-2 difference (look-ahead minus myopic): SAR {gap:,} ± {error:,.0f} (one standard "
        f"error). {'Not' if abs(gap) < 2 * error else 'Possibly'} significant at about two "
        "standard errors.",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "lookahead.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "lookahead.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
