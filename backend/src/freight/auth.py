"""OIDC login establishes opaque sessions; database membership grants access."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import httpx2 as httpx
from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request, Response
from joserfc.errors import JoseError
from sqlalchemy import delete, select
from starlette.concurrency import run_in_threadpool

from freight.db import Audit, LoginSession, Membership, session_factory
from freight.settings import get_settings

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@lru_cache
def oidc_client() -> Any:
    settings = get_settings()
    oauth = OAuth()
    return oauth.register(
        "workforce",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret.get_secret_value()
        if settings.oidc_client_secret
        else None,
        server_metadata_url=settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid", "code_challenge_method": "S256", "timeout": 15},
    )


def session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.cookie_name,
        token,
        httponly=True,
        secure=settings.freight_mode == "production",
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )


@router.get("/config")
def auth_config() -> dict[str, Any]:
    production = get_settings().freight_mode == "production"
    return {
        "mode": "production" if production else "demo",
        "login_url": "/api/auth/login" if production else None,
    }


@router.get("/login")
async def start_login(request: Request) -> Response:
    settings = get_settings()
    if settings.freight_mode != "production":
        raise HTTPException(404, "SSO is enabled only in production configuration")
    request.session.clear()
    nonce = secrets.token_urlsafe(32)
    request.session["expected_nonce"] = nonce
    try:
        response: Response = await oidc_client().authorize_redirect(
            request, settings.public_origin.rstrip("/") + "/api/auth/callback", nonce=nonce
        )
        return response
    except (OAuthError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, "The sign-in provider is unavailable. Try again later.") from exc


@router.get("/callback")
async def finish_login(request: Request) -> Response:
    settings = get_settings()
    if settings.freight_mode != "production":
        raise HTTPException(404, "SSO is enabled only in production configuration")
    expected_nonce = request.session.pop("expected_nonce", None)
    try:
        token = await oidc_client().authorize_access_token(
            request,
            claims_options={"iss": {"essential": True, "value": settings.oidc_issuer}},
            leeway=30,
        )
        claims = token.get("userinfo")
        # Require the nonce even if a provider claims nonce_supported=false.
        if (
            not expected_nonce
            or not claims
            or claims.get("nonce") != expected_nonce
            or claims.get("iss") != settings.oidc_issuer
            or not isinstance(claims.get("sub"), str)
        ):
            raise ValueError("Required OIDC claims missing or invalid")
        subject = claims["sub"]
        if not subject or len(subject) > 255:
            raise ValueError("Invalid subject")
    except (OAuthError, JoseError, httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(401, "Sign-in could not be verified. Start sign-in again.") from exc
    finally:
        request.session.clear()
    from fastapi.responses import RedirectResponse

    response = RedirectResponse(settings.public_origin.rstrip("/"), status_code=303)
    opaque = await run_in_threadpool(
        create_identity_session, subject, request.cookies.get(settings.cookie_name)
    )
    session_cookie(response, opaque)
    return response


def create_identity_session(subject: str, old: str | None) -> str:
    settings = get_settings()
    with session_factory().begin() as db:
        membership = db.scalar(
            select(Membership)
            .where(
                Membership.issuer == settings.oidc_issuer,
                Membership.subject == subject,
                Membership.active.is_(True),
            )
            .order_by(Membership.tenant_id)
            .limit(1)
        )
        if membership is None:
            raise HTTPException(
                403,
                "Your identity has no active workspace membership. Contact your workspace administrator.",
            )
        if old:
            db.execute(
                delete(LoginSession).where(
                    LoginSession.token_hash == hashlib.sha256(old.encode()).hexdigest()
                )
            )
        opaque = secrets.token_urlsafe(32)
        db.add(
            LoginSession(
                token_hash=hashlib.sha256(opaque.encode()).hexdigest(),
                tenant_id=membership.tenant_id,
                issuer=settings.oidc_issuer,
                subject=subject,
                expires_at=datetime.now(UTC) + timedelta(hours=settings.session_hours),
            )
        )
        db.add(
            Audit(
                tenant_id=membership.tenant_id,
                actor=f"{settings.oidc_issuer}|{subject}",
                kind="sign_in",
                data={"role": membership.role},
            )
        )
    return opaque
