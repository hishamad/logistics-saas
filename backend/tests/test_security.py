"""Production basics: sign-in throttling, users, audit trail, conflicts, headers."""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_api import PASSWORD, WRITE, app, login  # noqa: F401  (fixture)

from freight.api.app import serve_web_app
from freight.api.db import Database, User
from freight.api.store import load, save


def attempt(client: TestClient, email: str, password: str) -> int:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}, headers=WRITE
    )
    return response.status_code


def test_repeated_wrong_passwords_lock_the_email_for_a_while(app):  # noqa: F811
    with TestClient(app) as client:
        for _ in range(5):
            assert attempt(client, "dispatcher@east.test", "wrong") == 401
        # Even the right password is refused now, so guessing cannot continue.
        assert attempt(client, "dispatcher@east.test", PASSWORD) == 429
        # Other accounts are unaffected.
        assert attempt(client, "viewer@east.test", PASSWORD) == 200


def test_unknown_emails_get_the_same_answer_as_wrong_passwords(app):  # noqa: F811
    with TestClient(app) as client:
        assert attempt(client, "nobody@east.test", "x") == 401
        assert attempt(client, "dispatcher@east.test", "x") == 401


def test_admin_manages_users_and_deactivation_signs_them_out(app):  # noqa: F811
    admin = login(app, "admin@east.test")
    created = admin.post(
        "/api/users",
        json={
            "email": "New@East.test",
            "name": "New one",
            "role": "viewer",
            "password": "long-enough-1",
        },
        headers=WRITE,
    )
    assert created.status_code == 201 and created.json()["email"] == "new@east.test"
    newcomer = login_with(app, "new@east.test", "long-enough-1")
    assert newcomer.get("/api/me").json()["user"]["role"] == "viewer"
    promoted = admin.patch(
        f"/api/users/{created.json()['id']}", json={"role": "dispatcher"}, headers=WRITE
    )
    assert promoted.json()["role"] == "dispatcher"
    admin.patch(f"/api/users/{created.json()['id']}", json={"active": False}, headers=WRITE)
    assert newcomer.get("/api/me").status_code == 401
    assert attempt(TestClient(app), "new@east.test", "long-enough-1") == 401
    emails = [u["email"] for u in admin.get("/api/users").json()]
    assert "dispatcher@west.test" not in emails  # only this company's users


def test_only_admins_manage_users_and_nobody_changes_their_own_access(app):  # noqa: F811
    dispatcher = login(app, "dispatcher@east.test")
    assert dispatcher.get("/api/users").status_code == 403
    admin = login(app, "admin@east.test")
    me = next(u for u in admin.get("/api/users").json() if u["email"] == "admin@east.test")
    assert (
        admin.patch(f"/api/users/{me['id']}", json={"role": "viewer"}, headers=WRITE).status_code
        == 409
    )
    west = login(app, "admin@west.test")
    assert (
        west.patch(f"/api/users/{me['id']}", json={"active": False}, headers=WRITE).status_code
        == 404
    )


def test_password_change_needs_the_current_one_and_signs_out_elsewhere(app):  # noqa: F811
    first = login(app, "viewer@east.test")
    second = login(app, "viewer@east.test")
    wrong = first.post(
        "/api/me/password", json={"current": "nope", "new": "a-new-password"}, headers=WRITE
    )
    assert wrong.status_code == 403
    ok = first.post(
        "/api/me/password", json={"current": PASSWORD, "new": "a-new-password"}, headers=WRITE
    )
    assert ok.status_code == 200
    assert second.get("/api/me").status_code == 401
    assert login_with(app, "viewer@east.test", "a-new-password").get("/api/me").status_code == 200


def test_changes_are_in_the_audit_trail_with_who_did_them(app):  # noqa: F811
    client = login(app, "dispatcher@east.test")
    catalog = client.get("/api/steering").json()
    window = {"start": catalog["horizon"]["start"], "end": catalog["horizon"]["end"]}
    rule = {
        "kind": "resource_unavailable",
        "resource_id": catalog["teams"][0]["tractor_id"],
        "window": window,
    }
    client.post("/api/rules", json=rule, headers=WRITE)
    sheet = client.get("/api/data/jobs.xlsx").content
    client.post(
        "/api/data/jobs", params={"apply": True}, files={"file": ("o.xlsx", sheet)}, headers=WRITE
    )
    trail = client.get("/api/audit").json()
    assert [e["action"] for e in trail[:2]] == ["orders.upload", "rule.add"]
    assert {e["by"] for e in trail[:2]} == {"Eastern Carrier dispatcher"}
    assert all(e["action"] != "user.sign_in" for e in trail)  # sign-ins: admins only
    assert any(
        e["action"] == "user.sign_in"
        for e in login(app, "admin@east.test").get("/api/audit").json()
    )
    west = login(app, "dispatcher@west.test").get("/api/audit").json()
    assert all(e["by"] != "Eastern Carrier dispatcher" for e in west)


def test_a_save_based_on_an_old_version_is_refused(app):  # noqa: F811
    from fastapi import HTTPException

    with app.state.database.session() as session:
        user = session.query(User).filter_by(email="dispatcher@east.test").one()
        snapshot, version = load(session, "east")
        save(session, user, snapshot, based_on=version, action="test")
        with pytest.raises(HTTPException) as stale:
            save(session, user, snapshot, based_on=version, action="test")
        assert stale.value.status_code == 409
        assert load(session, "east")[1] == version + 1


def test_responses_carry_security_headers(app):  # noqa: F811
    with TestClient(app) as client:
        headers = client.get("/api/health").headers
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_the_built_web_app_is_served_with_routes_falling_back_to_it(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    web = FastAPI()
    serve_web_app(web, tmp_path)
    with TestClient(web) as client:
        assert client.get("/board").text == "<div id=root></div>"
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/api/nothing").status_code == 404
        assert client.get("/../secret").text == "<div id=root></div>"


def test_an_older_database_gets_new_columns_added(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:  # the users table as it was before "active"
        db.execute(
            "create table users (id varchar(32) primary key, company_id varchar(32), "
            "email varchar(254) unique, name varchar(150), role varchar(20), "
            "password_hash varchar(300), created_at datetime)"
        )
        db.execute("insert into users values ('u', 'c', 'a@b.c', 'A', 'viewer', 'x', null)")
    database = Database(f"sqlite:///{path.as_posix()}")
    with database.session() as session:
        assert session.get_one(User, "u").active is True


def login_with(app, email: str, password: str) -> TestClient:  # noqa: F811
    client = TestClient(app)
    client.__enter__()
    assert attempt(client, email, password) == 200
    return client
