"""The web API: login, tenant isolation, roles and background plan runs."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

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
            for role in ("admin", "dispatcher", "viewer"):
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


def done_plan(client: TestClient, **settings) -> dict:
    started = client.post("/api/plans", json={"rounds": 200, **settings}, headers=WRITE)
    assert started.status_code == 202, started.text
    run = wait_for(client, started.json()["id"])
    assert run["status"] == "done"
    return run


def test_why_explains_a_job_in_both_languages(app):
    client = login(app, "dispatcher@east.test")
    run = done_plan(client)
    board = client.get(f"/api/plans/{run['id']}/board").json()
    job = next(act[3] for team in board["teams"] for act in team["acts"] if act[3])
    english = client.get(f"/api/plans/{run['id']}/why/{job}").json()
    arabic = client.get(f"/api/plans/{run['id']}/why/{job}", params={"lang": "ar"}).json()
    assert english["source"] == "template" and english["facts"]["assigned"]
    assert board["jobs"][job]["ref"] in english["text"]
    assert "أُسندت" in arabic["text"]
    assert client.get(f"/api/plans/{run['id']}/why/nope").status_code == 404


def test_what_if_runs_in_the_background(app):
    client = login(app, "dispatcher@east.test")
    run = done_plan(client)
    job = client.get("/api/steering").json()["jobs"][0]["id"]
    started = client.post(
        f"/api/plans/{run['id']}/whatif",
        json={"kind": "drop", "job": job, "method": "replan"},
        headers=WRITE,
    )
    assert started.status_code == 202, started.text
    for _ in range(400):
        question = client.get(f"/api/whatif/{started.json()['id']}").json()
        if question["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert question["status"] == "done", question
    assert set(question["result"]["text"]) == {"en", "ar"}
    assert "difference" in question["result"]["facts"]
    incomplete = client.post(
        f"/api/plans/{run['id']}/whatif", json={"kind": "assign", "job": job}, headers=WRITE
    )
    assert incomplete.status_code == 422
    other = login(app, "dispatcher@west.test")
    assert other.get(f"/api/whatif/{started.json()['id']}").status_code == 404


def test_rules_are_checked_added_and_removed(app):
    client = login(app, "dispatcher@east.test")
    catalog = client.get("/api/steering").json()
    team = catalog["teams"][0]
    window = {"start": catalog["horizon"]["start"], "end": catalog["horizon"]["end"]}
    rule = {"kind": "resource_unavailable", "resource_id": team["tractor_id"], "window": window}
    added = client.post("/api/rules", json=rule, headers=WRITE)
    assert added.status_code == 200, added.text
    assert [r["id"] for r in client.get("/api/steering").json()["rules"]] == [added.json()["id"]]
    missing_window = client.post(
        "/api/rules",
        json={"kind": "resource_unavailable", "resource_id": team["tractor_id"]},
        headers=WRITE,
    )
    assert missing_window.status_code == 422
    unknown = client.post("/api/rules", json=rule | {"resource_id": "ghost"}, headers=WRITE)
    assert unknown.status_code == 422
    assert client.delete(f"/api/rules/{added.json()['id']}", headers=WRITE).status_code == 200
    assert client.get("/api/steering").json()["rules"] == []
    viewer = login(app, "viewer@east.test")
    assert viewer.post("/api/rules", json=rule, headers=WRITE).status_code == 403


def test_interpreting_without_ai_explains_and_changes_nothing(app):
    client = login(app, "dispatcher@east.test")
    version = client.get("/api/steering").json()["version"]
    result = client.post(
        "/api/rules/interpret", json={"text": "الشاحنة 1 في الورشة غداً"}, headers=WRITE
    ).json()
    assert result["status"] == "error" and result["rule"] is None
    assert client.get("/api/steering").json()["version"] == version


def test_freezing_and_stable_replanning(app):
    client = login(app, "dispatcher@east.test")
    first = done_plan(client)
    assert first["summary"]["changed"] is None  # nothing to be stable against yet
    frozen = client.post(
        "/api/locks/freeze", json={"run_id": first["id"], "hours": 168}, headers=WRITE
    ).json()
    assert frozen["frozen"] == first["summary"]["served"] + first["summary"]["offers_taken"]
    locks = client.get("/api/steering").json()["locks"]
    second = done_plan(client)
    assert second["summary"]["changed"] == 0  # every job frozen on its truck
    board = client.get(f"/api/plans/{second['id']}/board").json()
    assert sorted(board["frozen"]) == sorted(lock["job_id"] for lock in locks)
    assert client.delete(f"/api/locks/{locks[0]['job_id']}", headers=WRITE).status_code == 200
    assert len(client.get("/api/steering").json()["locks"]) == len(locks) - 1
    bad = client.post(
        "/api/locks", json={"job_id": "ghost", "team_id": locks[0]["team_id"]}, headers=WRITE
    )
    assert bad.status_code == 422
    assert client.delete("/api/locks", headers=WRITE).status_code == 200
    assert client.get("/api/steering").json()["locks"] == []


def make_offer(app, company_id: str) -> str:
    """Turn the company's first job into a well-paid spot load; return its id."""
    from freight.domain.models import Snapshot

    with app.state.database.session.begin() as db:
        row = db.get(Operation, company_id)
        snapshot = Snapshot.model_validate_json(row.snapshot)
        first = snapshot.jobs[0].model_copy(update={"state": "offered", "revenue_minor": 5_000_000})
        row.snapshot = snapshot.model_copy(
            update={"jobs": (first, *snapshot.jobs[1:])}
        ).model_dump_json()
        return first.id


def test_freezing_a_taken_spot_load_accepts_it_and_the_next_plan_still_works(app):
    offer = make_offer(app, "east")
    client = login(app, "dispatcher@east.test")
    first = done_plan(client)
    assert first["summary"]["offers_taken"] == 1
    frozen = client.post(
        "/api/locks/freeze", json={"run_id": first["id"], "hours": 168}, headers=WRITE
    ).json()
    assert frozen["accepted"] == 1
    job = next(j for j in client.get("/api/steering").json()["jobs"] if j["id"] == offer)
    assert job["state"] == "confirmed"
    second = done_plan(client)
    assert second["summary"]["valid"] is True
    assert second["summary"]["served"] == first["summary"]["served"] + 1


def test_orders_after_the_window_wait_instead_of_blocking_the_plan(app):
    client = login(app, "dispatcher@east.test")
    window = client.get("/api/data").json()["window"]
    total = sum(client.get("/api/data").json()["jobs"][k] for k in ("contract", "spot"))
    start = datetime.fromisoformat(window["start"]) - timedelta(days=2)  # all work starts later
    earlier = client.post(
        "/api/data/window", json={"start": start.isoformat(), "days": 1}, headers=WRITE
    )
    assert earlier.status_code == 200
    assert client.get("/api/data").json()["jobs"]["later"] == total
    run = done_plan(client)
    assert run["summary"]["valid"] and run["summary"]["confirmed"] == 0


def test_rolling_forward_to_the_next_day(app):
    client = login(app, "dispatcher@east.test")
    assert client.post("/api/data/roll", json={}, headers=WRITE).status_code == 409  # no plan
    first = done_plan(client)
    before = client.get("/api/data").json()
    report = client.post("/api/data/roll", json={"hours": 12}, headers=WRITE).json()
    assert report["window"]["start"] > before["window"]["start"]
    after = client.get("/api/data").json()
    assert after["version"] == before["version"] + 1
    left = after["jobs"]["contract"] + after["jobs"]["spot"]
    assert left == before["jobs"]["contract"] + before["jobs"]["spot"] - report["executed"] - len(
        report["missed"]
    )
    second = done_plan(client)
    assert second["summary"]["valid"], second
    assert first["id"] != second["id"]


def test_a_plan_the_engine_refuses_is_a_failed_run_with_its_reasons(app):
    from freight.domain.models import AssignmentLock, Snapshot

    with app.state.database.session.begin() as db:  # bypass the API's guard on purpose
        row = db.get(Operation, "east")
        snapshot = Snapshot.model_validate_json(row.snapshot)
        offer = snapshot.jobs[0].model_copy(update={"state": "offered"})
        lock = AssignmentLock(job_id=offer.id, team_id=snapshot.teams[0].id)
        jobs = (offer, *snapshot.jobs[1:])
        row.snapshot = snapshot.model_copy(
            update={"jobs": jobs, "locks": (lock,)}
        ).model_dump_json()
    client = login(app, "dispatcher@east.test")
    started = client.post("/api/plans", json={"rounds": 50}, headers=WRITE).json()
    run = wait_for(client, started["id"])
    assert run["status"] == "failed"
    assert "Only confirmed jobs can be locked" in run["error"]


def test_what_if_cancelling_a_frozen_job_works(app):
    client = login(app, "dispatcher@east.test")
    run = done_plan(client)
    client.post("/api/locks/freeze", json={"run_id": run["id"], "hours": 168}, headers=WRITE)
    job = client.get("/api/steering").json()["locks"][0]["job_id"]
    started = client.post(
        f"/api/plans/{run['id']}/whatif", json={"kind": "drop", "job": job}, headers=WRITE
    )
    for _ in range(400):
        question = client.get(f"/api/whatif/{started.json()['id']}").json()
        if question["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert question["status"] == "done", question
    assert question["result"]["facts"]["after"]["contribution_sar"] is not None


def test_changes_since_the_last_plan_and_excel_export(app):
    client = login(app, "dispatcher@east.test")
    first = done_plan(client)
    assert client.get(f"/api/plans/{first['id']}/changes").json() == {
        "against": None,
        "changes": None,
    }
    second = done_plan(client)
    answer = client.get(f"/api/plans/{second['id']}/changes").json()
    assert answer["against"]["id"] == first["id"]
    assert {"moved", "retimed", "added", "dropped", "notify", "unchanged"} <= set(answer["changes"])
    explicit = client.get(
        f"/api/plans/{first['id']}/changes", params={"against": second["id"]}
    ).json()
    assert explicit["against"]["id"] == second["id"]
    sheet = client.get(f"/api/plans/{second['id']}/export.xlsx", params={"lang": "ar"})
    assert sheet.status_code == 200 and sheet.content[:2] == b"PK"
    assert client.get("/api/plans").json()[0]["created_by"] == "Eastern Carrier dispatcher"
    other = login(app, "dispatcher@west.test")
    assert other.get(f"/api/plans/{second['id']}/export.xlsx").status_code == 404
    assert other.get(f"/api/plans/{second['id']}/changes").status_code == 404


def test_only_runs_that_cannot_still_be_alive_are_failed(app, tmp_path):
    """A second server on the same database must not fail a plan that is still running."""
    from freight.api.db import PlanRun, utcnow

    with app.state.database.session.begin() as db:
        user = db.query(User).filter_by(email="dispatcher@east.test").one()
        for run_id, age in (("dead", timedelta(minutes=20)), ("alive", timedelta(seconds=5))):
            db.add(
                PlanRun(
                    id=run_id,
                    company_id="east",
                    created_by=user.id,
                    created_at=utcnow() - age,
                    settings='{"seconds": 15}',
                    snapshot="{}",
                    status="running",
                )
            )
    url = str(app.state.database.engine.url)
    second = create_app(url, ThreadPoolExecutor(1))  # e.g. a restart overlap
    with TestClient(second):
        pass
    client = login(app, "dispatcher@east.test")
    dead, alive = client.get("/api/plans/dead").json(), client.get("/api/plans/alive").json()
    assert dead["status"] == "failed" and "server restarted" in dead["error"]
    assert alive["status"] == "running"


def test_a_freeze_that_became_impossible_is_released_not_fatal(app):
    client = login(app, "dispatcher@east.test")
    first = done_plan(client)
    board = client.get(f"/api/plans/{first['id']}/board").json()
    team = next(t for t in board["teams"] if any(act[3] for act in t["acts"]))
    job = next(act[3] for act in team["acts"] if act[3])
    assert (
        client.post(
            "/api/locks", json={"job_id": job, "team_id": team["id"]}, headers=WRITE
        ).status_code
        == 200
    )
    catalog = client.get("/api/steering").json()
    tractor = next(t["tractor_id"] for t in catalog["teams"] if t["id"] == team["id"])
    window = {"start": catalog["horizon"]["start"], "end": catalog["horizon"]["end"]}
    rule = {"kind": "resource_unavailable", "resource_id": tractor, "window": window}
    assert client.post("/api/rules", json=rule, headers=WRITE).status_code == 200
    second = done_plan(client)
    assert second["summary"]["valid"], second["summary"]
    assert second["summary"]["released_locks"] == [board["jobs"][job]["ref"]]
    assert client.get(f"/api/plans/{second['id']}/board").json()["released"] == [job]


def test_a_repair_what_if_is_answered_at_once_and_the_same_every_time(app):
    client = login(app, "dispatcher@east.test")
    run = done_plan(client)
    job = next(
        act[3]
        for team in client.get(f"/api/plans/{run['id']}/board").json()["teams"]
        for act in team["acts"]
        if act[3]
    )
    answers = [
        client.post(
            f"/api/plans/{run['id']}/whatif", json={"kind": "drop", "job": job}, headers=WRITE
        ).json()
        for _ in range(2)
    ]
    assert [a["status"] for a in answers] == ["done", "done"]
    assert answers[0]["result"]["facts"] == answers[1]["result"]["facts"]
    assert answers[0]["result"]["facts"]["method"] == "repair"


def test_the_overview_says_what_needs_attention(app):
    client = login(app, "dispatcher@east.test")
    kinds = lambda: {item["kind"] for item in client.get("/api/overview").json()["attention"]}  # noqa: E731
    assert "no_plan" in kinds()
    assert "window_behind" in kinds()  # the fixture's window is days before today
    done_plan(client)
    first = client.get("/api/overview").json()
    assert first["latest"]["settings"]["operation_version"] == first["operation"]["version"]
    assert {"no_plan", "plan_out_of_date"}.isdisjoint(kinds())
    sheet = client.get("/api/data/jobs.xlsx").content
    client.post(
        "/api/data/jobs", params={"apply": True}, files={"file": ("o.xlsx", sheet)}, headers=WRITE
    )
    assert "plan_out_of_date" in kinds()


def test_the_dispatcher_confirms_what_was_done_before_the_next_day(app):
    client = login(app, "dispatcher@east.test")
    done_plan(client)
    preview = client.get("/api/data/roll", params={"hours": 24}).json()
    assert preview["jobs"], "the demo plan starts work in its first day"
    skipped = preview["jobs"][0]
    before = client.get("/api/data").json()
    report = client.post(
        "/api/data/roll", json={"hours": 24, "not_done": [skipped["job"]]}, headers=WRITE
    ).json()
    missed = {m["ref"] for m in report["missed"]}
    assert (set(report["not_done"]) | missed) >= {skipped["ref"]}
    assert not set(report["not_done"]) & missed  # each order reported once
    assert report["executed"] == len(preview["jobs"]) - 1
    open_refs = {j["reference"] for j in client.get("/api/steering").json()["jobs"]}
    assert skipped["ref"] in open_refs | missed
    trail = client.get("/api/audit").json()
    assert trail[0]["action"] == "window.next_day" and trail[0]["detail"]["not_done"] == [
        skipped["ref"]
    ]
    assert before["version"] + 1 == client.get("/api/data").json()["version"]


def test_the_next_day_needs_a_plan_made_for_the_current_window(app):
    client = login(app, "dispatcher@east.test")
    done_plan(client)
    window = client.get("/api/data").json()["window"]
    moved = datetime.fromisoformat(window["start"]) + timedelta(hours=6)
    client.post("/api/data/window", json={"start": moved.isoformat(), "days": 2}, headers=WRITE)
    refused = client.get("/api/data/roll")
    assert refused.status_code == 409 and "different planning window" in refused.json()["detail"]
    assert client.post("/api/data/roll", json={}, headers=WRITE).status_code == 409


def test_the_network_map_has_real_sites_and_the_lanes_the_plan_drives(app):
    from pathlib import Path

    pilot = Path(__file__).parents[2] / "data" / "saudi" / "scenarios" / "pilot" / "snapshot.json"
    with app.state.database.session.begin() as db:
        db.get(Operation, "east").snapshot = pilot.read_text(encoding="utf-8")
    client = login(app, "dispatcher@east.test")
    before = client.get("/api/network").json()
    riyadh = next(s for s in before["sites"] if s["id"] == "riyadh")
    assert 24 < riyadh["lat"] < 25 and 46 < riyadh["lon"] < 47
    assert before["lanes"] == []  # no plan yet
    done_plan(client)
    after = client.get("/api/network").json()
    assert after["lanes"] and all(lane["trips"] >= 1 for lane in after["lanes"])
    ids = {s["id"] for s in after["sites"]}
    assert all(lane["from"] in ids and lane["to"] in ids for lane in after["lanes"])
    assert sum(s["trucks"] for s in after["sites"]) > 0
    west = login(app, "dispatcher@west.test").get("/api/network").json()
    assert west["sites"] == []  # the other company's demo sites have no map position
