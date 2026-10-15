"""The web API around the planning engine.

    uv run uvicorn freight.api.app:create_app --factory --reload

Every request is tied to a logged-in user, and every query is filtered by that
user's company, so one carrier can never see another's data. Requests that
change something must carry the header ``X-Requested-With: freight`` (a simple
defence against cross-site request forgery for a same-origin web app).
"""

import json
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import Executor, ProcessPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from freight.api.db import Company, Database, LoginSession, Operation, PlanRun, User, utcnow
from freight.api.runner import Runner
from freight.api.security import hash_token, new_token, verify_password
from freight.board import board_data
from freight.domain.models import Plan, Snapshot
from freight.settings import get_settings
from freight.sheets import (
    Kind,
    SheetError,
    import_fleet,
    import_jobs,
    read_rows,
    set_window,
    workbook,
)

COOKIE = "freight_session"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def iso(value: datetime) -> str:
    """ISO time in UTC. SQLite returns stored times without their timezone."""
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class PlanRequest(BaseModel):
    seconds: float = Field(default=30, ge=1, le=300)
    rounds: int | None = Field(default=None, ge=1, le=200_000)
    seed: int = 1
    lookahead: bool = False


class WindowRequest(BaseModel):
    start: datetime
    days: int = Field(ge=1, le=7)


def create_app(database_url: str | None = None, executor: Executor | None = None) -> FastAPI:
    settings = get_settings()
    url = database_url or settings.database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    database = Database(url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        pool = executor or ProcessPoolExecutor(max_workers=settings.plan_workers)
        app.state.runner = Runner(pool, database.session)
        yield
        pool.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Freight planning API", lifespan=lifespan)
    app.state.database = database

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method not in ("GET", "HEAD", "OPTIONS") and (
            request.headers.get("x-requested-with") != "freight"
        ):
            return JSONResponse({"detail": "Missing X-Requested-With header"}, status_code=403)
        return await call_next(request)

    def db() -> Iterator[Session]:
        with database.session() as session:
            yield session

    Db = Annotated[Session, Depends(db)]

    def current_user(request: Request, session: Db) -> User:
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in")
        found = session.get(LoginSession, hash_token(token))
        if found is None or found.expires_at.replace(tzinfo=utcnow().tzinfo) < utcnow():
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
        return session.get_one(User, found.user_id)

    Me = Annotated[User, Depends(current_user)]

    def dispatcher(user: Me) -> User:
        if user.role != "dispatcher":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Viewers cannot change plans")
        return user

    def operation_of(session: Session, company_id: str) -> Snapshot:
        row = session.get(Operation, company_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No operation set up yet")
        return Snapshot.model_validate_json(row.snapshot)

    def run_of(session: Session, user: User, run_id: str) -> PlanRun:
        run = session.get(PlanRun, run_id)
        if run is None or run.company_id != user.company_id:  # never reveal other tenants
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
        return run

    def run_view(run: PlanRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "status": run.status,
            "created_at": iso(run.created_at),
            "finished_at": iso(run.finished_at) if run.finished_at else None,
            "settings": json.loads(run.settings),
            "summary": json.loads(run.summary) if run.summary else None,
            "error": "The planning engine failed; see the server log." if run.error else None,
        }

    @app.post("/api/auth/login")
    def login(body: LoginRequest, response: Response, session: Db) -> dict[str, Any]:
        user = session.scalar(select(User).where(User.email == body.email.strip().lower()))
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
        token = new_token()
        session.add(
            LoginSession(
                token_hash=hash_token(token),
                user_id=user.id,
                expires_at=utcnow() + timedelta(hours=settings.session_hours),
            )
        )
        session.commit()
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure,
            max_age=settings.session_hours * 3600,
        )
        return me_view(session, user)

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, session: Db) -> dict[str, bool]:
        token = request.cookies.get(COOKIE)
        if token and (found := session.get(LoginSession, hash_token(token))):
            session.delete(found)
            session.commit()
        response.delete_cookie(COOKIE)
        return {"ok": True}

    def me_view(session: Session, user: User) -> dict[str, Any]:
        company = session.get_one(Company, user.company_id)
        return {
            "user": {"name": user.name, "email": user.email, "role": user.role},
            "company": {"name": company.name},
        }

    @app.get("/api/me")
    def me(user: Me, session: Db) -> dict[str, Any]:
        return me_view(session, user)

    @app.get("/api/operation")
    def operation(user: Me, session: Db) -> dict[str, Any]:
        snapshot = operation_of(session, user.company_id)
        row = session.get_one(Operation, user.company_id)
        return {
            "name": snapshot.name,
            "version": row.version,
            "updated_at": iso(row.updated_at),
            "horizon": snapshot.horizon.model_dump(mode="json"),
            "trucks": len(snapshot.teams),
            "sites": len(snapshot.sites),
            "jobs_confirmed": sum(j.state == "confirmed" for j in snapshot.jobs),
            "jobs_offered": sum(j.state == "offered" for j in snapshot.jobs),
            "driving_rules": snapshot.driving_rules is not None,
        }

    @app.post("/api/plans", status_code=status.HTTP_202_ACCEPTED)
    def start_plan(
        body: PlanRequest, request: Request, session: Db, user: Annotated[User, Depends(dispatcher)]
    ) -> dict[str, Any]:
        snapshot = operation_of(session, user.company_id)
        run = PlanRun(
            company_id=user.company_id,
            created_by=user.id,
            settings=body.model_dump_json(),
            snapshot=snapshot.model_dump_json(),
        )
        session.add(run)
        session.commit()
        request.app.state.runner.submit(run.id, run.snapshot, body.model_dump())
        session.refresh(run)
        return run_view(run)

    @app.get("/api/plans")
    def list_plans(user: Me, session: Db) -> list[dict[str, Any]]:
        runs = session.scalars(
            select(PlanRun)
            .where(PlanRun.company_id == user.company_id)
            .order_by(PlanRun.created_at.desc())
            .limit(50)
        )
        return [run_view(run) for run in runs]

    @app.get("/api/plans/{run_id}")
    def get_plan(run_id: str, user: Me, session: Db) -> dict[str, Any]:
        return run_view(run_of(session, user, run_id))

    @app.get("/api/plans/{run_id}/board")
    def get_board(run_id: str, user: Me, session: Db) -> dict[str, object]:
        run = run_of(session, user, run_id)
        if run.status != "done" or run.plan is None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Plan is {run.status}")
        return board_data(
            Snapshot.model_validate_json(run.snapshot), Plan.model_validate_json(run.plan)
        )

    # --- data in: planning window, orders and fleet ------------------------------------

    def save_operation(session: Session, company_id: str, snapshot: Snapshot) -> int:
        row = session.get_one(Operation, company_id)
        row.snapshot = snapshot.model_dump_json()
        row.version += 1
        row.updated_at = utcnow()
        session.commit()
        return row.version

    @app.get("/api/data")
    def data_overview(user: Me, session: Db) -> dict[str, Any]:
        snapshot = operation_of(session, user.company_id)
        row = session.get_one(Operation, user.company_id)
        horizon = snapshot.horizon
        depots: dict[str, int] = {}
        for team in snapshot.teams:
            depots[snapshot.home_of(team)] = depots.get(snapshot.home_of(team), 0) + 1
        return {
            "version": row.version,
            "updated_at": iso(row.updated_at),
            "window": {"start": horizon.start.isoformat(), "end": horizon.end.isoformat()},
            "jobs": {
                "contract": sum(j.state == "confirmed" for j in snapshot.jobs),
                "spot": sum(j.state == "offered" for j in snapshot.jobs),
                "outside_window": sum(
                    j.pickup_window.start >= horizon.end or j.delivery_window.end <= horizon.start
                    for j in snapshot.jobs
                ),
                "customers": len({j.customer for j in snapshot.jobs}),
            },
            "fleet": {
                "trucks": len(snapshot.teams),
                "depots": depots,
                "dry_van": sum(
                    r.kind == "trailer" and r.equipment == "dry_van" for r in snapshot.resources
                ),
                "flatbed": sum(
                    r.kind == "trailer" and r.equipment == "flatbed" for r in snapshot.resources
                ),
            },
            "sites": [s.model_dump() for s in snapshot.sites],
            "locks": len(snapshot.locks),
            "rules": len(snapshot.rules),
        }

    @app.post("/api/data/window")
    def change_window(
        body: WindowRequest, session: Db, user: Annotated[User, Depends(dispatcher)]
    ) -> dict[str, Any]:
        if body.start.tzinfo is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Start needs a timezone")
        snapshot = set_window(operation_of(session, user.company_id), body.start, body.days)
        return {"version": save_operation(session, user.company_id, snapshot)}

    @app.get("/api/data/{kind}.xlsx")
    def download_sheet(kind: Kind, user: Me, session: Db, template: bool = False) -> Response:
        snapshot = operation_of(session, user.company_id)
        name = ("orders" if kind == "jobs" else "fleet") + ("-template" if template else "")
        return Response(
            workbook(snapshot, kind, template=template),
            media_type=XLSX,
            headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
        )

    @app.post("/api/data/{kind}")
    async def upload_sheet(
        kind: Kind,
        session: Db,
        user: Annotated[User, Depends(dispatcher)],
        file: Annotated[UploadFile, File()],
        apply: bool = False,
        version: int | None = None,
    ) -> dict[str, Any]:
        """Check an uploaded sheet; with ``apply`` (and no problems) replace the data."""
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
        snapshot = operation_of(session, user.company_id)
        row = session.get_one(Operation, user.company_id)
        try:
            rows = read_rows(file.filename or "", content, kind)
        except SheetError as error:
            return {
                "applied": False,
                "file_error": error.code,
                "detail": error.detail,
                "problems": [],
                "summary": {},
            }
        outcome = (import_jobs if kind == "jobs" else import_fleet)(snapshot, rows)
        result: dict[str, Any] = {
            "applied": False,
            "file_error": None,
            "problems": [vars(p) for p in outcome.problems[:500]],
            "problem_count": len(outcome.problems),
            "summary": outcome.summary,
            "version": row.version,
        }
        if apply and outcome.snapshot is not None:
            if version is not None and version != row.version:
                raise HTTPException(status.HTTP_409_CONFLICT, "The data changed; check again")
            result["version"] = save_operation(session, user.company_id, outcome.snapshot)
            result["applied"] = True
        return result

    return app
