"""Explanations: computed facts first, words second, and a template when AI fails."""

from contextlib import nullcontext
from types import SimpleNamespace

import httpx
from openai import APIConnectionError

from freight import explain
from freight.fixtures import demo_snapshot
from freight.planning.engine import plan_lns
from freight.settings import Settings


def planned():
    snapshot = demo_snapshot(job_count=8, team_count=4)
    return snapshot, plan_lns(snapshot, rounds=300, seed=1)


def test_why_compares_the_chosen_truck_with_its_alternatives():
    snapshot, plan = planned()
    job_id = plan.assignments[0].job_id
    facts = explain.why(snapshot, plan, job_id)
    chosen = facts["assigned"]
    assert chosen["truck"] in {t.name for t in snapshot.teams}
    for alternative in facts["alternatives"]:
        assert alternative["more_than_chosen_sar"] == (
            alternative["extra_cost_sar"] - chosen["extra_cost_sar"]
        )
    others = facts["other_trucks_that_could_take_it"] + sum(
        facts["trucks_that_cannot_take_it"].values()
    )
    assert others == len(snapshot.teams) - 1


def test_what_if_a_job_is_cancelled_isolates_its_effect():
    snapshot, plan = planned()
    job_id = plan.assignments[0].job_id
    facts, _, after = explain.what_if(snapshot, plan, {"kind": "drop", "job": job_id}, rounds=200)
    assert facts["new_plan_valid"] and after.valid
    assert facts["difference"]["contract_jobs_served"] == -1
    assert job_id not in {a.job_id for a in after.assignments}
    assert "cancelled" in facts["change"] and facts["change_ar"]


def test_narration_uses_the_model_and_falls_back_to_the_template(monkeypatch):
    snapshot, plan = planned()
    facts = explain.why(snapshot, plan, plan.assignments[0].job_id)
    settings = Settings(openai_api_key="offline-test", openai_model_rules="offline-model")
    monkeypatch.setattr(explain, "get_settings", lambda: settings)

    def answer(**kwargs):
        assert kwargs["store"] is False and "ONLY the facts" in kwargs["instructions"]
        return SimpleNamespace(status="completed", output_text="Because it is closest.", model="m")

    client = SimpleNamespace(responses=SimpleNamespace(create=answer))
    monkeypatch.setattr(explain, "OpenAI", lambda **_: nullcontext(client))
    assert explain.narrate(facts) == ("Because it is closest.", "AI (m)")

    def fail(**_):
        raise APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))

    client.responses.create = fail
    text, source = explain.narrate(facts, "ar")
    assert source == "template" and "الشحنة" in text
