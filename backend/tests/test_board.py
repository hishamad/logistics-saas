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
