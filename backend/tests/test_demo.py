"""The carrier demo: a simulated week written as a small static website."""

import json
import re

from freight.demo import build_demo
from freight.fixtures import demo_snapshot


def embedded(html: str) -> dict:
    match = re.search(r"const DATA = (.*?);\n", html)
    assert match, "page data not embedded"
    return json.loads(match.group(1).replace("<\\/", "</"))


def test_demo_writes_a_summary_and_one_board_per_morning(tmp_path):
    base = demo_snapshot(job_count=10, team_count=4).model_copy(update={"return_to_start": False})
    data = build_demo(base, tmp_path, days=2, seconds=1)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["day-1.html", "day-2.html", "index.html"]
    summary = embedded((tmp_path / "index.html").read_text(encoding="utf-8"))
    assert summary["result"] == data["result"]
    assert summary["result"]["valid_days"] == 2
    assert [m["file"] for m in summary["mornings"]] == ["day-1.html", "day-2.html"]
    first = embedded((tmp_path / "day-1.html").read_text(encoding="utf-8"))
    second = embedded((tmp_path / "day-2.html").read_text(encoding="utf-8"))
    assert first["changes"] is None and first["nav"]["next"] == "day-2.html"
    assert second["changes"] is not None and second["nav"]["prev"] == "day-1.html"


def test_a_fixed_number_of_rounds_makes_the_demo_repeatable(tmp_path):
    base = demo_snapshot(job_count=10, team_count=4).model_copy(update={"return_to_start": False})
    first = build_demo(base, tmp_path / "a", days=2, rounds=150)
    second = build_demo(base, tmp_path / "b", days=2, rounds=150)
    assert first["result"] == second["result"]
