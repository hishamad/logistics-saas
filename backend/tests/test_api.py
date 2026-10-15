"""The web API: login, tenant isolation, roles and background plan runs."""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from freight.api.app import create_app
from freight.api.db import Company, Operation, User
from freight.api.security import hash_password
from freight.fixtures import demo_snapshot

WRITE = {"X-Requested-With": "freight"}
PASSWORD = "test-only-password"


@pytest.fixture
def app(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", ThreadPoolExecutor(2))
    snapshot = demo_snapshot(job_count=8, team_count=4).model_dump_json()
    with app.state.database.session.begin() as db:
        for company_id, name in (("east", "Eastern Carrier"), ("west", "Western Carrier")):
            db.add(Company(id=company_id, name=name))
            db.flush()
            db.add(Operation(company_id=company_id, snapshot=snapshot))
            for role in ("dispatcher", "viewer"):
                db.add(
                    User(
                        company_id=company_id,
                        email=f"{role}@{company_id}.test",
                        name=f"{name} {role}",
                        role=role,
                        password_hash=hash_password(PASSWORD),
                    )
                )
    return app


def login(app, email: str) -> TestClient:
    client = TestClient(app)
    client.__enter__()
    response = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}, headers=WRITE
    )
    assert response.status_code == 200, response.text
    return client


def wait_for(client: TestClient, run_id: str) -> dict:
    for _ in range(200):
        run = client.get(f"/api/plans/{run_id}").json()
        if run["status"] in ("done", "failed"):
            return run
        time.sleep(0.05)
    raise AssertionError("plan did not finish")


def test_login_is_required_and_wrong_passwords_fail(app):
    with TestClient(app) as client:
        assert client.get("/api/me").status_code == 401
        wrong = client.post(
            "/api/auth/login",
            json={"email": "dispatcher@east.test", "password": "nope"},
            headers=WRITE,
        )
        assert wrong.status_code == 401
    client = login(app, "dispatcher@east.test")
    assert client.get("/api/me").json()["company"]["name"] == "Eastern Carrier"
    assert client.post("/api/auth/logout", headers=WRITE).status_code == 200
    assert client.get("/api/me").status_code == 401


def test_writes_without_the_header_are_refused(app):
    client = login(app, "dispatcher@east.test")
    assert client.post("/api/plans", json={"rounds": 50}).status_code == 403


def test_a_plan_runs_in_the_background_and_its_board_loads(app):
    client = login(app, "dispatcher@east.test")
    started = client.post("/api/plans", json={"rounds": 200, "seconds": 30}, headers=WRITE)
    assert started.status_code == 202
    run = wait_for(client, started.json()["id"])
    assert run["status"] == "done", run
    assert run["summary"]["valid"] and run["summary"]["served"] == run["summary"]["confirmed"]
    board = client.get(f"/api/plans/{run['id']}/board").json()
    assert board["valid"] and len(board["teams"]) == 4
    assert [r["id"] for r in client.get("/api/plans").json()] == [run["id"]]


def test_companies_never_see_each_others_plans(app):
    east = login(app, "dispatcher@east.test")
    run_id = east.post("/api/plans", json={"rounds": 50}, headers=WRITE).json()["id"]
    wait_for(east, run_id)
    west = login(app, "dispatcher@west.test")
    assert west.get(f"/api/plans/{run_id}").status_code == 404
    assert west.get(f"/api/plans/{run_id}/board").status_code == 404
    assert west.get("/api/plans").json() == []


def test_viewers_can_look_but_not_plan(app):
    viewer = login(app, "viewer@east.test")
    assert viewer.get("/api/operation").json()["trucks"] == 4
    assert viewer.post("/api/plans", json={"rounds": 50}, headers=WRITE).status_code == 403


def upload(client: TestClient, kind: str, content: bytes, name: str, **params) -> dict:
    response = client.post(
        f"/api/data/{kind}",
        params=params,
        files={"file": (name, content)},
        headers=WRITE,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_orders_round_trip_check_then_apply(app):
    client = login(app, "dispatcher@east.test")
    before = client.get("/api/data").json()
    sheet = client.get("/api/data/jobs.xlsx")
    assert sheet.status_code == 200
    assert sheet.headers["content-type"].startswith("application/vnd.openxmlformats")

    checked = upload(client, "jobs", sheet.content, "orders.xlsx")
    assert checked["applied"] is False and checked["problems"] == []
    assert checked["summary"]["kept"] == before["jobs"]["contract"] + before["jobs"]["spot"]

    applied = upload(
        client, "jobs", sheet.content, "orders.xlsx", apply=True, version=before["version"]
    )
    assert applied["applied"] is True
    assert client.get("/api/data").json()["version"] == before["version"] + 1

    stale = client.post(
        "/api/data/jobs",
        params={"apply": True, "version": before["version"]},
        files={"file": ("orders.xlsx", sheet.content)},
        headers=WRITE,
    )
    assert stale.status_code == 409


def test_bad_uploads_change_nothing(app):
    client = login(app, "dispatcher@east.test")
    version = client.get("/api/data").json()["version"]
    bad = b"reference,customer\nA,B\n"
    result = upload(client, "jobs", bad, "orders.csv", apply=True)
    assert result["applied"] is False and result["file_error"] == "missing_columns"
    template = client.get("/api/data/fleet.xlsx", params={"template": True}).content
    result = upload(client, "fleet", template, "fleet.xlsx", apply=True)
    assert result["applied"] is False  # template sites are not in the demo network
    assert "unknown_site" in {p["code"] for p in result["problems"]}
    assert client.get("/api/data").json()["version"] == version


def test_viewers_cannot_upload_and_companies_stay_apart(app):
    viewer = login(app, "viewer@east.test")
    sheet = viewer.get("/api/data/jobs.xlsx").content
    refused = viewer.post("/api/data/jobs", files={"file": ("o.xlsx", sheet)}, headers=WRITE)
    assert refused.status_code == 403
    east = login(app, "dispatcher@east.test")
    west = login(app, "dispatcher@west.test")
    empty = upload(east, "jobs", b"", "empty.csv")
    assert empty["file_error"] == "no_header"
    applied = upload(east, "fleet", east.get("/api/data/fleet.xlsx").content, "f.xlsx", apply=True)
    assert applied["applied"] is True
    assert west.get("/api/data").json()["version"] == 1


def test_window_moves(app):
    client = login(app, "dispatcher@east.test")
    start = client.get("/api/data").json()["window"]["start"]
    moved = client.post("/api/data/window", json={"start": start, "days": 2}, headers=WRITE)
    assert moved.status_code == 200
    window = client.get("/api/data").json()["window"]
    assert window["start"] == start and window["end"] != start
    assert (
        client.post("/api/data/window", json={"start": start, "days": 9}, headers=WRITE).status_code
        == 422
    )
