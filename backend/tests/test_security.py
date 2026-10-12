"""Production authorization and real signed-token OIDC contract tests."""

import hashlib
import importlib
import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from pydantic import ValidationError

from freight.db import LoginSession, Membership, session_factory
from freight.settings import Settings, get_settings


def test_production_configuration_fails_closed():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, freight_mode="production")


@pytest.fixture
def production(clients, monkeypatch):
    from freight import auth
    from freight.api import app as module

    original = get_settings()
    settings = Settings(
        _env_file=None,
        freight_mode="production",
        database_url=original.database_url,
        public_origin="https://freight.test",
        allowed_hosts=["freight.test"],
        freight_allowed_origins=["https://freight.test"],
        oidc_issuer="https://identity.test",
        oidc_client_id="freight-client",
        oidc_client_secret="offline-client-secret",
        session_signing_key=secrets.token_urlsafe(40),
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    # App construction reads configuration. Reload against the scoped test DB;
    # restore the original configuration before other fixtures create apps.
    monkeypatch.setattr("freight.settings.get_settings", lambda: settings)
    importlib.reload(module)
    with session_factory().begin() as db:
        db.add(
            Membership(
                tenant_id="eastern-demo",
                issuer=settings.oidc_issuer,
                subject="dispatcher-1",
                role="dispatcher",
                active=True,
            )
        )
        db.add(
            Membership(
                tenant_id="western-demo",
                issuer=settings.oidc_issuer,
                subject="viewer-1",
                role="viewer",
                active=True,
            )
        )
    try:
        with TestClient(
            module.app, base_url="https://freight.test", headers={"X-Freight-Request": "1"}
        ) as client:
            yield client, settings
    finally:
        monkeypatch.undo()
        auth.oidc_client.cache_clear()
        importlib.reload(module)


def issue_session(client, settings, subject, tenant):
    token = secrets.token_urlsafe(32)
    with session_factory().begin() as db:
        db.add(
            LoginSession(
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
                tenant_id=tenant,
                issuer=settings.oidc_issuer,
                subject=subject,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    client.cookies.set(settings.cookie_name, token)


def test_production_disables_demo_and_checks_membership_on_every_request(production):
    client, settings = production
    assert client.get("/api/demo-workspaces").status_code == 404
    assert client.post("/api/session", json={"tenant_id": "eastern-demo"}).status_code == 404
    assert client.get("/api/workspace").status_code == 401
    issue_session(client, settings, "viewer-1", "western-demo")
    assert client.get("/api/workspace").json()["role"] == "viewer"
    assert client.put("/api/locks", json={"expected_version": 1, "locks": []}).status_code == 403
    with session_factory().begin() as db:
        db.get(Membership, ("western-demo", settings.oidc_issuer, "viewer-1")).active = False
    assert client.get("/api/workspace").status_code == 403
    assert client.delete("/api/session").status_code == 200


@pytest.mark.parametrize(
    "fault", [None, "nonce", "aud", "iss", "expired", "unknown-user", "state", "signature"]
)
def test_oidc_code_flow_validates_real_signed_claims_and_membership(production, monkeypatch, fault):
    from authlib.integrations.starlette_client import OAuth

    from freight import auth

    client, settings = production
    key = RSAKey.generate_key(2048)
    key.ensure_kid()
    authorization = {}

    def provider(request):
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": settings.oidc_issuer,
                    "authorization_endpoint": settings.oidc_issuer + "/authorize",
                    "token_endpoint": settings.oidc_issuer + "/token",
                    "jwks_uri": settings.oidc_issuer + "/jwks",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [key.as_dict(private=False)]})
        if request.url.path == "/token":
            posted = parse_qs(request.content.decode())
            assert posted["code"] == ["single-use-test-code"]
            assert posted["code_verifier"]
            claims = {
                "iss": settings.oidc_issuer,
                "sub": "dispatcher-1",
                "aud": "freight-client",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "nonce": authorization["nonce"][0],
            }
            if fault in ("nonce", "aud", "iss"):
                claims[fault] = "incorrect"
            if fault == "expired":
                claims["exp"] = int(time.time()) - 600
            if fault == "unknown-user":
                claims["sub"] = "not-provisioned"
            signing_key = RSAKey.generate_key(2048) if fault == "signature" else key
            signed = jwt.encode({"alg": "RS256", "kid": key.kid}, claims, signing_key)
            return httpx.Response(
                200,
                json={"access_token": "offline-access", "token_type": "Bearer", "id_token": signed},
            )
        raise AssertionError(f"Unexpected provider endpoint {request.url.path}")

    oauth = OAuth()
    remote = oauth.register(
        "test",
        client_id=settings.oidc_client_id,
        client_secret="offline-secret",
        server_metadata_url=settings.oidc_issuer + "/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid",
            "code_challenge_method": "S256",
            "transport": httpx.MockTransport(provider),
        },
    )
    monkeypatch.setattr(auth, "oidc_client", lambda: remote)
    start = client.get("/api/auth/login", follow_redirects=False)
    assert start.status_code == 302
    authorization.update(parse_qs(urlsplit(start.headers["location"]).query))
    assert authorization["code_challenge_method"] == ["S256"]
    callback = client.get(
        "/api/auth/callback",
        params={
            "code": "single-use-test-code",
            "state": "wrong" if fault == "state" else authorization["state"][0],
        },
        follow_redirects=False,
    )
    assert callback.status_code == (
        303 if fault is None else 403 if fault == "unknown-user" else 401
    ), callback.text
    if fault is None:
        cookie = callback.headers.get("set-cookie", "")
        assert "__Host-freight_session=" in cookie and "Secure" in cookie and "HttpOnly" in cookie
        assert client.get("/api/workspace").json()["snapshot"]["tenant_id"] == "eastern-demo"
        assert client.get("/api/audit").json()[0]["actor"] == "https://identity.test|dispatcher-1"
    else:
        assert client.get("/api/workspace").status_code == 401


def test_host_csrf_and_bounded_body_are_enforced(clients):
    client, _ = clients
    assert client.get("/api/workspace", headers={"Host": "attacker.invalid"}).status_code == 400
    assert (
        client.put(
            "/api/locks",
            headers={"X-Freight-Request": ""},
            json={"expected_version": 1, "locks": []},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/imports", content=b"x" * 2_100_001, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.headers.get("x-request-id")
    assert client.get("/api/workspace").json()["version"] == 1


def test_exported_csv_formula_cells_are_safe_and_round_trip_unchanged(clients):
    from freight import imports
    from freight.domain.models import Snapshot

    client, _ = clients
    snapshot = client.get("/api/workspace").json()["snapshot"]
    snapshot["jobs"][0]["reference"] = '=HYPERLINK("https://invalid.test")'
    snapshot["jobs"][0]["customer"] = "'=literal apostrophe"
    job = snapshot["jobs"][0]
    assert (
        client.put(f"/api/jobs/{job['id']}", json={"expected_version": 1, "job": job}).status_code
        == 200
    )
    content = imports.template(Snapshot.model_validate(snapshot), "jobs")
    assert "apostrophe-v1" in content
    batch = client.post("/api/imports", json={"entity": "jobs", "content": content}).json()
    assert batch["rows"][0]["status"] == "unchanged"
    assert batch["rows"][0]["data"]["reference"] == job["reference"]
