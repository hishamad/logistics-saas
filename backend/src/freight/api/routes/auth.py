"""Signing in and out, passwords, the company's users and its audit trail."""

import json
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from freight.api.db import AuditEvent, Company, LoginFailure, LoginSession, User, utcnow
from freight.api.deps import COOKIE, Admin, Db, Me
from freight.api.schemas import LoginRequest, PasswordChange, UserCreate, UserUpdate
from freight.api.security import hash_password, hash_token, new_token, verify_password
from freight.api.store import audit, iso
from freight.settings import get_settings

router = APIRouter(prefix="/api")

# Checked against when the email is unknown, so a reply takes as long either way.
_DUMMY_HASH = hash_password("not-a-real-password")


def me_view(session: Session, user: User) -> dict[str, Any]:
    company = session.get_one(Company, user.company_id)
    return {
        "user": {"name": user.name, "email": user.email, "role": user.role},
        "company": {"name": company.name},
    }


def _throttled(session: Session, email: str, address: str) -> bool:
    settings = get_settings()
    since = utcnow() - timedelta(minutes=settings.login_window_minutes)
    session.execute(delete(LoginFailure).where(LoginFailure.at < since))
    by_email = session.scalar(
        select(func.count()).where(LoginFailure.email == email, LoginFailure.at >= since)
    )
    by_address = session.scalar(
        select(func.count()).where(LoginFailure.address == address, LoginFailure.at >= since)
    )
    return (by_email or 0) >= settings.login_max_failures or (
        by_address or 0
    ) >= 4 * settings.login_max_failures


@router.post("/auth/login")
def login(body: LoginRequest, request: Request, response: Response, session: Db) -> dict[str, Any]:
    settings = get_settings()
    email = body.email.strip().lower()
    address = request.client.host if request.client else "unknown"
    if _throttled(session, email, address):
        session.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed sign-ins. Wait a few minutes and try again.",
            headers={"Retry-After": str(settings.login_window_minutes * 60)},
        )
    user = session.scalar(select(User).where(User.email == email))
    good = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not good or not user.active:
        session.add(LoginFailure(email=email, address=address))
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    session.execute(delete(LoginFailure).where(LoginFailure.email == email))
    session.execute(delete(LoginSession).where(LoginSession.expires_at < utcnow()))
    token = new_token()
    session.add(
        LoginSession(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=settings.session_hours),
        )
    )
    audit(session, user, "user.sign_in")
    session.commit()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        max_age=settings.session_hours * 3600,
    )
    return me_view(session, user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, session: Db) -> dict[str, bool]:
    token = request.cookies.get(COOKIE)
    if token and (found := session.get(LoginSession, hash_token(token))):
        session.delete(found)
        session.commit()
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: Me, session: Db) -> dict[str, Any]:
    return me_view(session, user)


@router.post("/me/password")
def change_password(body: PasswordChange, user: Me, session: Db) -> dict[str, bool]:
    if not verify_password(body.current, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The current password is wrong")
    user.password_hash = hash_password(body.new)
    # Sign out every other session of this user.
    session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    audit(session, user, "user.password")
    session.commit()
    return {"ok": True}


def user_view(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "active": user.active,
        "created_at": iso(user.created_at),
    }


@router.get("/users")
def list_users(user: Admin, session: Db) -> list[dict[str, Any]]:
    users = session.scalars(
        select(User).where(User.company_id == user.company_id).order_by(User.created_at)
    )
    return [user_view(u) for u in users]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, user: Admin, session: Db) -> dict[str, Any]:
    email = body.email.strip().lower()
    if session.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This email already has an account")
    created = User(
        company_id=user.company_id,
        email=email,
        name=body.name.strip(),
        role=body.role,
        password_hash=hash_password(body.password),
    )
    session.add(created)
    session.flush()
    audit(session, user, "user.create", {"email": email, "role": body.role})
    session.commit()
    return user_view(created)


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserUpdate, user: Admin, session: Db) -> dict[str, Any]:
    target = session.get(User, user_id)
    if target is None or target.company_id != user.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if target.id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot change your own access")
    if body.role is not None:
        target.role = body.role
    if body.active is not None:
        target.active = body.active
        if not body.active:
            session.execute(delete(LoginSession).where(LoginSession.user_id == target.id))
    audit(
        session, user, "user.update", {"email": target.email, **body.model_dump(exclude_none=True)}
    )
    session.commit()
    return user_view(target)


@router.get("/audit")
def audit_trail(user: Me, session: Db, limit: int = 200) -> list[dict[str, Any]]:
    """Who changed what, newest first (sign-ins only for admins)."""
    query = select(AuditEvent).where(AuditEvent.company_id == user.company_id)
    if user.role != "admin":
        query = query.where(AuditEvent.action != "user.sign_in")
    events = session.scalars(query.order_by(AuditEvent.at.desc()).limit(min(limit, 1000)))
    names = {
        row.id: row.name
        for row in session.execute(
            select(User.id, User.name).where(User.company_id == user.company_id)
        )
    }
    return [
        {
            "at": iso(e.at),
            "by": names.get(e.user_id or "", None),
            "action": e.action,
            "detail": json.loads(e.detail),
        }
        for e in events
    ]
