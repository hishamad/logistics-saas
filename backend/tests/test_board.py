"""The HTML plan board embeds validated plan data safely."""

import json
import re

from freight.board import render_board
from freight.fixtures import demo_snapshot
from freight.planning.engine import plan_lns


def embedded(html: str) -> dict:
    match = re.search(r"const DATA = (.*?);\n", html)
    assert match, "board data not embedded"
    return json.loads(match.group(1).replace("<\\/", "</"))


def test_board_embeds_the_plan_figures():
    snapshot = demo_snapshot()
    plan = plan_lns(snapshot, seconds=1)
    data = embedded(render_board(snapshot, plan))
    assert data["valid"] is True
    assert data["kpis"]["served"] == data["kpis"]["confirmed"] == 8
    assert len(data["teams"]) == len(snapshot.teams)
    assert sum(len(t["acts"]) for t in data["teams"]) == len(plan.activities)
    assert data["kpis"]["empty_km"] == round(plan.costs.empty_distance_m / 1000)


def test_customer_text_cannot_close_the_script_element():
    snapshot = demo_snapshot()
    hostile = "</script><script>alert(1)</script>"
    jobs = tuple(j.model_copy(update={"customer": hostile}) for j in snapshot.jobs)
    snapshot = snapshot.model_copy(update={"jobs": jobs})
    html = render_board(snapshot, plan_lns(snapshot, seconds=1))
    assert html.count("</script>") == 1  # only the template's own closing tag
    assert embedded(html)["jobs"][jobs[0].id]["customer"] == hostile


def test_the_board_shows_when_a_truck_cannot_work():
    from datetime import timedelta

    from freight.board import board_data
    from freight.domain.models import Rule, Window

    snapshot = demo_snapshot()
    team = snapshot.teams[0]
    start = snapshot.horizon.start
    workshop = Rule(
        id="r1",
        kind="resource_unavailable",
        resource_id=team.tractor_id,
        window=Window(start=start + timedelta(hours=8), end=start + timedelta(hours=14)),
    )
    snapshot = snapshot.model_copy(update={"rules": (workshop,)})
    data = board_data(snapshot, plan_lns(snapshot, seconds=1))
    blocks = {t["id"]: t["blocks"] for t in data["teams"]}
    assert blocks[team.id] == [(8 * 60, 14 * 60, "rule")]
    assert all(not b for tid, b in blocks.items() if tid != team.id)
    # The plan respects it: no work for that truck inside the window.
    acts = next(t["acts"] for t in data["teams"] if t["id"] == team.id)
    assert all(a[2] <= 8 * 60 or a[1] >= 14 * 60 for a in acts if a[0] != 4)
