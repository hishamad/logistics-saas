"""Who is asking: the database session, the signed-in user and their role."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from freight.api.db import LoginSession, User, utcnow
from freight.api.security import hash_token

COOKIE = "freight_session"
CAN_PLAN = ("admin", "dispatcher")


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.database.session() as session:
        yield session


Db = Annotated[Session, Depends(get_db)]


def current_user(request: Request, session: Db) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
    found = session.get(LoginSession, hash_token(token))
    if found is None or found.expires_at.replace(tzinfo=utcnow().tzinfo) < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = session.get_one(User, found.user_id)
    if not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account deactivated")
    return user


Me = Annotated[User, Depends(current_user)]


def dispatcher(user: Me) -> User:
    if user.role not in CAN_PLAN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Viewers cannot change plans")
    return user


Dispatcher = Annotated[User, Depends(dispatcher)]


def admin(user: Me) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can manage users")
    return user


Admin = Annotated[User, Depends(admin)]
