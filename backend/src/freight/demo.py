"""The carrier demo: a simulated dispatch week as a small static website.

    freight demo ../data/saudi/scenarios/full/snapshot.json --out ../boards/demo

Writes index.html (a bilingual result sheet) and one plan board per morning with
"changes since yesterday". Everything opens in a browser without a server.
"""

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from freight.board import render_board
from freight.domain.models import Plan, Snapshot
from freight.planning.daily import simulate
from freight.planning.diff import PlanDiff

TEMPLATE = Path(__file__).with_name("demo_template.html")


def build_demo(
    base: Snapshot,
    out: Path,
    *,
    days: int = 7,
    seconds: float = 15,
    seed: int = 1,
    freeze_hours: float = 6,
    change_penalty_minor: int = 30_000,
    rounds: int | None = None,
) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    mornings: list[dict[str, str]] = []

    def write_morning(day: int, snapshot: Snapshot, plan: Plan, changes: PlanDiff | None) -> None:
        file = f"day-{day + 1}.html"
        start = snapshot.horizon.start
        nav = {
            "home": "index.html",
            "prev": f"day-{day}.html" if day > 0 else "",
            "next": f"day-{day + 2}.html" if day + 1 < days else "",
            "label": f"Morning {day + 1} of {days}",
        }
        (out / file).write_text(render_board(snapshot, plan, changes, nav), encoding="utf-8")
        mornings.append({"file": file, "iso": start.isoformat()})

    result = simulate(
        base,
        days=days,
        seconds=seconds,
        seed=seed,
        freeze_hours=freeze_hours,
        change_penalty_minor=change_penalty_minor,
        on_morning=write_morning,
        rounds=rounds,
    )
    sites = {s.id: s for s in base.sites}
    homes = Counter(base.home_of(t) for t in base.teams)
    data = {
        "generated": datetime.now(UTC).strftime("%Y-%m-%d"),
        "scenario": base.name,
        "trucks": len(base.teams),
        "days": days,
        "depots": [
            {
                "name_en": sites[site].name,
                "name_ar": sites[site].name_ar or sites[site].name,
                "count": count,
            }
            for site, count in homes.most_common()
        ],
        "settings": {
            "freeze_hours": freeze_hours,
            "change_penalty_sar": change_penalty_minor // 100,
            "seconds": seconds,
            "rounds": rounds,
            "seed": seed,
        },
        "result": result,
        "mornings": mornings,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    (out / "index.html").write_text(page, encoding="utf-8")
    return data
