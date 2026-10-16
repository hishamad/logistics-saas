"""Explanations: computed facts first, words second, and a template when AI fails."""

from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace

import httpx
from openai import APIConnectionError

from freight import explain
from freight.domain.models import Rule, Window
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
    facts, _, after = explain.what_if(
        snapshot, plan, {"kind": "drop", "job": job_id}, method="replan", rounds=200
    )
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


def test_a_repair_is_exact_repeatable_and_keeps_untouched_trucks():
    snapshot, plan = planned()
    victim = plan.assignments[0]
    change = {"kind": "drop", "job": victim.job_id}
    first, _, repaired = explain.what_if(snapshot, plan, change)
    second, _, _ = explain.what_if(snapshot, plan, change)
    assert first == second and first["method"] == "repair"
    # Trucks the cancelled job did not touch keep exactly the same work.
    before = {a.job_id: a.team_id for a in plan.assignments}
    after = {a.job_id: a.team_id for a in repaired.assignments}
    for job_id, team in before.items():
        if team != victim.team_id and job_id in after:
            assert after[job_id] == team


def test_a_repair_only_moves_the_jobs_that_clash_with_unavailability():
    snapshot, plan = planned()
    busy = plan.assignments[0]
    start, end = busy.pickup_at - timedelta(minutes=1), busy.released_at
    change = {"kind": "unavailable", "team": busy.team_id, "start": start, "end": end}
    facts, _, repaired = explain.what_if(snapshot, plan, change)
    assert repaired.valid
    assert not any(
        a.team_id == busy.team_id and a.pickup_at < end and a.released_at > start
        for a in repaired.assignments
    )


def test_a_job_its_target_truck_can_never_do_is_reported_as_impossible():
    snapshot, plan = planned()
    target = snapshot.teams[0]
    rule = Rule(
        id="off",
        kind="resource_unavailable",
        resource_id=target.tractor_id,
        window=Window(start=snapshot.horizon.start, end=snapshot.horizon.end + timedelta(days=9)),
    )
    blocked = snapshot.model_copy(update={"rules": (rule,)})
    job_id = next(a.job_id for a in plan.assignments if a.team_id != target.id)
    try:
        explain.what_if(blocked, plan, {"kind": "assign", "job": job_id, "team": target.id})
    except explain.WhatIfImpossible as impossible:
        assert target.name in impossible.english and target.name in impossible.arabic
    else:
        raise AssertionError("expected the assignment to be impossible")


def test_an_unplanned_job_says_when_trucks_are_busy_rather_than_unable():
    snapshot = demo_snapshot(job_count=8, team_count=1)  # more work than one truck can do
    plan = plan_lns(snapshot, rounds=200, seed=1)
    confirmed = {j.id for j in snapshot.jobs if j.state == "confirmed"}
    left = [j for j in plan.unserved_job_ids if j in confirmed]
    assert left, "the fixture should leave work unplanned"
    reasons = [explain.why(snapshot, plan, j)["trucks_that_cannot_take_it"] for j in left]
    assert any(r.get("busy with other work") == 1 for r in reasons)
