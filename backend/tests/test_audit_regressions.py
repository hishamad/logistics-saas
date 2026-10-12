"""Regression cases found during the production-readiness audit."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Event
from uuid import uuid4

import pytest
from pydantic import ValidationError

from freight import ai
from freight.domain.models import CostProfile, Lane, Rule, Snapshot, Window
from freight.domain.time import overlaps
from freight.fixtures import demo_snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.solver import solve_plan


def test_empty_intervals_do_not_overlap_but_positive_intervals_do():
    origin = demo_snapshot().horizon.start
    end = origin + timedelta(hours=2)
    point = origin + timedelta(hours=1)
    assert not overlaps(point, point, origin, end)
    assert not overlaps(origin, end, point, point)
    assert overlaps(origin, end, point, end)


def test_impossible_lane_and_unknown_manual_customer_are_rejected():
    with pytest.raises(ValidationError):
        Lane(from_site_id="a", to_site_id="b", distance_m=500, duration_minutes=0)
    with pytest.raises(ValidationError):
        Lane(from_site_id="a", to_site_id="a", distance_m=500, duration_minutes=5)
    snapshot = demo_snapshot()
    rule = Rule(
        id="bad-customer", kind="customer_eligibility", team_id="team-01", customer="unknown"
    )
    with pytest.raises(ValidationError):
        Snapshot.model_validate(snapshot.model_dump() | {"rules": [rule]})


def test_baseline_reschedules_idle_terminal_move_around_busy_window():
    snapshot = demo_snapshot(job_count=0, team_count=1)
    origin = snapshot.horizon.start
    busy = Window(start=origin, end=origin + timedelta(hours=2))
    snapshot = snapshot.model_copy(
        update={
            "rules": (
                Rule(id="busy", kind="resource_unavailable", resource_id="driver-01", window=busy),
                Rule(
                    id="return",
                    kind="required_end",
                    team_id="team-01",
                    site_id="port",
                    window=Window(start=origin, end=origin + timedelta(hours=4)),
                ),
            )
        }
    )
    plan = baseline_plan(snapshot)
    assert plan.valid and plan.coverage == "complete", plan.findings
    assert plan.activities[0].start >= busy.end


def test_large_allowed_costs_do_not_overflow_dense_objective():
    snapshot = demo_snapshot(job_count=12, team_count=8)
    snapshot = snapshot.model_copy(
        update={
            "costs": CostProfile(
                distance_minor_per_km=Decimal("99999.99"), duty_minor_per_hour=Decimal("99999.99")
            ),
            "lanes": tuple(
                lane.model_copy(update={"distance_m": 10_000_000}) for lane in snapshot.lanes
            ),
        }
    )
    baseline = baseline_plan(snapshot)
    result = solve_plan(snapshot, seconds=3, hint=baseline)
    assert result.outcome != "model_invalid", result.findings
    assert result.valid, result.findings


@pytest.mark.integration
def test_unmapped_csv_fields_preserve_cancellation_and_service_values(clients):
    client, _ = clients
    job = client.get("/api/workspace").json()["snapshot"]["jobs"][0]
    job |= {"state": "cancelled", "loading_minutes": 71, "priority": 3}
    assert (
        client.put(f"/api/jobs/{job['id']}", json={"expected_version": 1, "job": job}).status_code
        == 200
    )
    batch = client.post(
        "/api/imports", json={"entity": "jobs", "content": f"id,weight_kg\n{job['id']},13000\n"}
    ).json()
    row = batch["rows"][0]
    assert row["status"] == "conflict"
    assert row["data"]["state"] == "cancelled"
    assert row["data"]["loading_minutes"] == 71
    assert row["data"]["priority"] == 3
    result = client.post(
        f"/api/imports/{batch['id']}/commit",
        json={
            "expected_version": 2,
            "lines": [2],
            "overrides": [2],
            "idempotency_key": str(uuid4()),
        },
    )
    assert result.status_code == 200, result.text


@pytest.mark.integration
def test_ai_retry_is_not_rebilled_and_does_not_lock_dispatcher_edits(clients, monkeypatch):
    client, _ = clients
    entered, release = Event(), Event()
    calls = []

    def provider(*_):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {
            "status": "clarification",
            "explanation": "Which job?",
            "question": "Which job?",
            "rule": None,
        }

    monkeypatch.setattr(ai, "propose_rule", provider)
    body = {"expected_version": 1, "text": "Assign the job", "idempotency_key": str(uuid4())}
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(client.post, "/api/rule-proposals", json=body)
        try:
            assert entered.wait(5)
            assert client.post("/api/rule-proposals", json=body).status_code == 409
            assert (
                client.put("/api/locks", json={"expected_version": 1, "locks": []}).status_code
                == 200
            )
        finally:
            release.set()
        result = future.result()
    assert result.status_code == 200, result.text
    assert client.post("/api/rule-proposals", json=body).json() == result.json()
    assert len(calls) == 1
    assert result.json()["base_version"] == 1


@pytest.mark.integration
def test_failed_ai_calls_consume_quota_and_retries_reuse_failure(clients, monkeypatch):
    client, _ = clients
    calls = []

    def provider(*_):
        calls.append(1)
        raise ai.InterpretationError("Synthetic provider failure")

    monkeypatch.setattr(ai, "propose_rule", provider)
    body = {"expected_version": 1, "text": "Assign the job", "idempotency_key": str(uuid4())}
    assert client.post("/api/rule-proposals", json=body).status_code == 503
    assert client.post("/api/rule-proposals", json=body).status_code == 503
    assert len(calls) == 1
    for _ in range(19):
        assert (
            client.post(
                "/api/rule-proposals", json=body | {"idempotency_key": str(uuid4())}
            ).status_code
            == 503
        )
    assert (
        client.post(
            "/api/rule-proposals", json=body | {"idempotency_key": str(uuid4())}
        ).status_code
        == 429
    )
    assert len(calls) == 20


@pytest.mark.integration
def test_health_detects_a_stalled_worker_queue(clients):
    from sqlalchemy import func, update

    from freight.db import Run, session_factory

    client, _ = clients
    queued = client.post(
        "/api/runs", json={"expected_version": 1, "idempotency_key": str(uuid4())}
    ).json()
    with session_factory().begin() as db:
        db.execute(
            update(Run)
            .where(Run.id == queued["id"])
            .values(created_at=func.now() - timedelta(minutes=6))
        )
    assert client.get("/health").status_code == 503
    assert client.post(f"/api/runs/{queued['id']}/cancel").status_code == 200
    assert client.get("/health").status_code == 200
