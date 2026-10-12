from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, update

from freight.db import Run, session_factory
from freight.workers.runner import claim_next, execute, fenced_update

pytestmark = pytest.mark.integration


def test_commit_failure_cannot_be_reported_as_success(clients):
    a, _ = clients
    from freight.api.app import app

    session_class = session_factory().class_

    def fail_commit(_):
        raise RuntimeError("Injected commit failure")

    event.listen(session_class, "before_commit", fail_commit)
    try:
        client = TestClient(
            app,
            raise_server_exceptions=False,
            headers={"X-Freight-Request": "1"},
            cookies={"freight_session": a.cookies.get("freight_session")},
        )
        response = client.put("/api/locks", json={"expected_version": 1, "locks": []})
        assert response.status_code == 500
        client.close()
    finally:
        event.remove(session_class, "before_commit", fail_commit)
    assert a.get("/api/workspace").json()["version"] == 1


def queue(client, **kwargs):
    return client.post(
        "/api/runs",
        json={
            "expected_version": client.get("/api/workspace").json()["version"],
            "seconds": 2,
            "idempotency_key": str(uuid4()),
            **kwargs,
        },
    )


def test_two_workers_cannot_claim_the_same_run(clients):
    a, _ = clients
    run_id = queue(a).json()["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim_next(), range(2)))
    claimed = [claim for claim in claims if claim is not None]
    assert len(claimed) == 1 and claimed[0].id == run_id
    assert a.get(f"/api/runs/{run_id}").json()["attempt"] == 1


def test_tenant_boundary_and_real_worker(clients):
    a, b = clients
    run_id = queue(a).json()["id"]
    assert b.get(f"/api/runs/{run_id}").status_code == 404
    assert b.post(f"/api/runs/{run_id}/cancel").status_code == 404
    claim = claim_next()
    assert claim and claim.id == run_id
    execute(claim)
    result = a.get(f"/api/runs/{run_id}").json()
    assert result["state"] == "succeeded", result
    assert result["result"]["candidate"]["valid"]
    assert result["result"]["candidate"]["coverage"] == "complete"
    assert (
        result["result"]["baseline"]["snapshot_hash"]
        == result["result"]["candidate"]["snapshot_hash"]
    )
    assert b.get("/api/runs").json() == []
    assert b.get(f"/api/runs/{run_id}/export").status_code == 404
    exported = a.get(f"/api/runs/{run_id}/export")
    assert exported.status_code == 200
    assert "SYNTHETIC REVIEW ONLY" in exported.text and "+03:00" in exported.text


def test_resource_batch_moves_fixed_team_atomically(clients):
    a, _ = clients
    content = a.get("/api/templates/resources").text.replace(",depot,", ",port,")
    batch = a.post("/api/imports", json={"entity": "resources", "content": content}).json()
    assert all(row["status"] == "conflict" for row in batch["rows"])
    body = {"expected_version": 1, "lines": [2], "overrides": [2], "idempotency_key": str(uuid4())}
    assert a.post(f"/api/imports/{batch['id']}/commit", json=body).status_code == 422
    assert a.get("/api/workspace").json()["version"] == 1
    assert (
        a.post(
            f"/api/imports/{batch['id']}/commit",
            json=body
            | {"lines": [2, 3, 4], "overrides": [2, 3, 4], "idempotency_key": str(uuid4())},
        ).status_code
        == 200
    )
    resources = a.get("/api/workspace").json()["snapshot"]["resources"]
    assert all(r["site_id"] == "port" for r in resources[:3])


def test_review_commit_retry_and_source_conflict(clients):
    a, b = clients
    content = a.get("/api/templates/jobs").text
    preview = a.post("/api/imports", json={"entity": "jobs", "content": content}).json()
    assert all(r["status"] == "unchanged" for r in preview["rows"])
    assert b.get(f"/api/imports/{preview['id']}").status_code == 404
    payload = {
        "expected_version": 1,
        "lines": [r["line"] for r in preview["rows"]],
        "overrides": [],
        "idempotency_key": str(uuid4()),
    }
    committed = a.post(f"/api/imports/{preview['id']}/commit", json=payload)
    assert committed.status_code == 200, committed.text
    assert a.post(f"/api/imports/{preview['id']}/commit", json=payload).json() == committed.json()
    changed_key = a.post(f"/api/imports/{preview['id']}/commit", json=payload | {"lines": [2]})
    assert changed_key.status_code == 409
    job = a.get("/api/workspace").json()["snapshot"]["jobs"][0]
    assert (
        a.put(
            f"/api/jobs/{job['id']}",
            json={"expected_version": 1, "job": job | {"weight_kg": 12000}},
        ).status_code
        == 200
    )
    refresh = a.post(
        "/api/imports", json={"entity": "jobs", "content": content.replace(",8000,", ",10000,")}
    ).json()
    assert refresh["rows"][0]["status"] == "conflict"
    body = payload | {"expected_version": 2, "lines": [2], "idempotency_key": str(uuid4())}
    assert a.post(f"/api/imports/{refresh['id']}/commit", json=body).status_code == 409
    assert (
        a.post(f"/api/imports/{refresh['id']}/commit", json=body | {"overrides": [2]}).status_code
        == 200
    )
    snapshot = a.get("/api/workspace").json()["snapshot"]
    assert len(snapshot["jobs"]) == 8 and snapshot["jobs"][0]["weight_kg"] == 10000


def test_stale_source_preview_cannot_overwrite_new_revision(clients):
    a, _ = clients
    preview = a.post(
        "/api/imports", json={"entity": "jobs", "content": a.get("/api/templates/jobs").text}
    ).json()
    assert a.put("/api/locks", json={"expected_version": 1, "locks": []}).status_code == 200
    response = a.post(
        f"/api/imports/{preview['id']}/commit",
        json={"expected_version": 1, "lines": [2], "idempotency_key": str(uuid4())},
    )
    assert response.status_code == 409


def test_malformed_csv_header_is_a_review_error_not_server_failure(clients):
    a, _ = clients
    response = a.post("/api/imports", json={"entity": "jobs", "content": '"unterminated header'})
    assert response.status_code == 422
    assert a.get("/api/workspace").json()["version"] == 1


def test_concurrent_edits_have_one_winner(clients):
    a, _ = clients

    def edit(_):
        return a.put("/api/locks", json={"expected_version": 1, "locks": []}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(edit, range(2))) == [200, 409]
    assert a.get("/api/workspace").json()["version"] == 2


def test_reclaimed_lease_and_cancellation_fence_old_writes(clients):
    a, _ = clients
    run_id = queue(a).json()["id"]
    old = claim_next()
    assert old and old.attempt == 1
    with session_factory().begin() as db:
        db.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(lease_until=func.now() - timedelta(seconds=1))
        )
    new = claim_next()
    assert new and new.attempt == 2
    assert not fenced_update(old, state="succeeded", result={"stale": True})
    assert a.post(f"/api/runs/{run_id}/cancel").json()["state"] == "cancelled"
    assert not fenced_update(new, state="succeeded", result={"cancelled": True})
    assert a.get(f"/api/runs/{run_id}").json()["result"] is None


def test_ai_absence_does_not_block_manual_planning_and_csrf_is_rejected(clients):
    a, _ = clients
    assert not a.get("/api/workspace").json()["ai_configured"]
    assert (
        a.post(
            "/api/rule-proposals",
            json={
                "expected_version": 1,
                "text": "Assign job 1 to team 2",
                "idempotency_key": str(uuid4()),
            },
        ).status_code
        == 503
    )
    assert a.get("/api/workspace").json()["version"] == 1
    assert (
        a.post(
            "/api/runs",
            headers={"Origin": "https://untrusted.invalid"},
            json={"expected_version": 1, "idempotency_key": str(uuid4())},
        ).status_code
        == 403
    )
    assert queue(a).status_code == 202


def test_ai_proposal_needs_explicit_current_revision_approval(clients, monkeypatch):
    a, b = clients
    from freight import ai
    from freight.domain.models import Rule

    # Explicit offline adapter fixture. This is not a live model-quality test.
    rule = Rule(id="fixture-rule", kind="preferred_assignment", job_id="job-001", team_id="team-02")
    monkeypatch.setattr(
        ai,
        "propose_rule",
        lambda *_: {
            "status": "proposed",
            "explanation": "Fixture rule",
            "question": None,
            "rule": rule.model_dump(mode="json"),
        },
    )
    proposal = a.post(
        "/api/rule-proposals",
        json={"expected_version": 1, "text": "Fixture request", "idempotency_key": str(uuid4())},
    ).json()
    assert a.get("/api/workspace").json()["snapshot"]["rules"] == []
    assert (
        b.post(
            f"/api/rule-proposals/{proposal['id']}/approve", json={"expected_version": 1}
        ).status_code
        == 404
    )
    assert (
        a.post(
            f"/api/rule-proposals/{proposal['id']}/approve", json={"expected_version": 1}
        ).status_code
        == 200
    )
    assert (
        a.post(
            f"/api/rule-proposals/{proposal['id']}/approve", json={"expected_version": 2}
        ).status_code
        == 200
    )
    assert len(a.get("/api/workspace").json()["snapshot"]["rules"]) == 1
