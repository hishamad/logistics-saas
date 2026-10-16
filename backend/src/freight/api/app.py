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
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from freight.ai import InterpretationError, propose_rule
from freight.api.db import (
    Company,
    Database,
    LoginSession,
    Operation,
    PlanRun,
    User,
    WhatIfRun,
    new_id,
    utcnow,
)
from freight.api.runner import Runner, fail_interrupted, is_safe_error
from freight.api.security import hash_token, new_token, verify_password
from freight.board import board_data
from freight.domain.models import AssignmentLock, Job, Plan, Rule, Snapshot
from freight.explain import narrate, why
from freight.handover import export_workbook, plan_changes
from freight.planning.engine import routes_of
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
from freight.validation.validator import input_findings

COOKIE = "freight_session"
RIYADH = ZoneInfo("Asia/Riyadh")
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
    # Start from the last plan and charge for moving a job to another truck, so a
    # re-plan only changes instructions already sent when that is worth it.
    stable: bool = True


# What a moved job costs in a stable re-plan (halalas): SAR 300.
CHANGE_PENALTY_MINOR = 30_000


class RuleRequest(BaseModel):
    """A rule without its id; the server assigns one."""

    kind: str
    resource_id: str | None = None
    team_id: str | None = None
    job_id: str | None = None
    site_id: str | None = None
    customer: str | None = None
    window: dict[str, datetime] | None = None
    strength: str = "hard"
    penalty_minor: int = 0
    source_text: str = Field(default="Rule form", max_length=2000)


class LockRequest(BaseModel):
    job_id: str
    team_id: str


class FreezeRequest(BaseModel):
    run_id: str
    hours: int = Field(ge=1, le=168)


class InterpretRequest(BaseModel):
    text: str = Field(min_length=2, max_length=1000)


class WhatIfRequest(BaseModel):
    kind: str
    job: str | None = None
    team: str | None = None
    start: datetime | None = None
    end: datetime | None = None


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
        fail_interrupted(database.session)
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

    def run_view(run: PlanRun, by: str | None = None) -> dict[str, Any]:
        return {
            "id": run.id,
            "created_by": by,
            "status": run.status,
            "created_at": iso(run.created_at),
            "finished_at": iso(run.finished_at) if run.finished_at else None,
            "settings": json.loads(run.settings),
            "summary": json.loads(run.summary) if run.summary else None,
            "error": (
                run.error
                if is_safe_error(run.error)
                else "The planning engine failed; see the server log."
                if run.error
                else None
            ),
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
        initial = None
        last = latest_done(session, user.company_id) if body.stable else None
        if last is not None and last.plan is not None:
            # Continue from the last plan and charge for moving jobs, so only changes
            # worth more than the disruption reach drivers.
            plan = Plan.model_validate_json(last.plan)
            initial = routes_of(plan)
            if not snapshot.previous:
                snapshot = with_previous(snapshot, plan)
        run = PlanRun(
            company_id=user.company_id,
            created_by=user.id,
            settings=body.model_dump_json(),
            snapshot=snapshot.model_dump_json(),
        )
        session.add(run)
        session.commit()
        request.app.state.runner.submit(run.id, run.snapshot, body.model_dump(), initial)
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
        names = {
            row.id: row.name
            for row in session.execute(
                select(User.id, User.name).where(User.company_id == user.company_id)
            )
        }
        return [run_view(run, names.get(run.created_by)) for run in runs]

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

    def done_plan_of(session: Session, user: User, run_id: str) -> tuple[PlanRun, Snapshot, Plan]:
        run = run_of(session, user, run_id)
        if run.status != "done" or run.plan is None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Plan is {run.status}")
        return run, Snapshot.model_validate_json(run.snapshot), Plan.model_validate_json(run.plan)

    def previous_done(session: Session, run: PlanRun) -> PlanRun | None:
        return session.scalar(
            select(PlanRun)
            .where(
                PlanRun.company_id == run.company_id,
                PlanRun.status == "done",
                PlanRun.created_at < run.created_at,
            )
            .order_by(PlanRun.created_at.desc())
            .limit(1)
        )

    def changes_between(
        session: Session, user: User, run_id: str, against: str | None
    ) -> tuple[dict[str, Any] | None, PlanRun | None]:
        run, snapshot, plan = done_plan_of(session, user, run_id)
        other = run_of(session, user, against) if against else previous_done(session, run)
        if other is None:
            return None, None
        _, before_snapshot, before = done_plan_of(session, user, other.id)
        return plan_changes(snapshot, plan, before_snapshot, before), other

    # --- hand-over: what changed, and the plan as Excel -------------------------------

    @app.get("/api/plans/{run_id}/changes")
    def get_changes(
        run_id: str, user: Me, session: Db, against: str | None = None
    ) -> dict[str, Any]:
        """Changes since ``against`` (default: the plan before this one)."""
        changes, other = changes_between(session, user, run_id, against)
        if other is None:
            return {"against": None, "changes": None}
        return {
            "against": {"id": other.id, "created_at": iso(other.created_at)},
            "changes": changes,
        }

    @app.get("/api/plans/{run_id}/export.xlsx")
    def export_plan(run_id: str, user: Me, session: Db, lang: str = "en") -> Response:
        run, snapshot, plan = done_plan_of(session, user, run_id)
        changes, _ = changes_between(session, user, run_id, None)
        language: Literal["en", "ar"] = "ar" if lang == "ar" else "en"
        created = run.created_at.replace(tzinfo=run.created_at.tzinfo or UTC)
        stamp = f"{created.astimezone(RIYADH):%Y-%m-%d-%H%M}"
        return Response(
            export_workbook(snapshot, plan, changes, language),
            media_type=XLSX,
            headers={"Content-Disposition": f'attachment; filename="plan-{stamp}.xlsx"'},
        )

    def latest_done(session: Session, company_id: str) -> PlanRun | None:
        return session.scalar(
            select(PlanRun)
            .where(PlanRun.company_id == company_id, PlanRun.status == "done")
            .order_by(PlanRun.created_at.desc())
            .limit(1)
        )

    def with_previous(snapshot: Snapshot, plan: Plan) -> Snapshot:
        jobs = {j.id for j in snapshot.jobs}
        teams = {t.id for t in snapshot.teams}
        previous = {
            a.job_id: a.team_id for a in plan.assignments if a.job_id in jobs and a.team_id in teams
        }
        return snapshot.model_copy(
            update={"previous": previous, "change_penalty_minor": CHANGE_PENALTY_MINOR}
        )

    # --- steering: why, what if, rules and frozen assignments -------------------------

    @app.get("/api/plans/{run_id}/why/{job_id}")
    def explain_job(
        run_id: str, job_id: str, user: Me, session: Db, lang: str = "en"
    ) -> dict[str, Any]:
        run = run_of(session, user, run_id)
        if run.status != "done" or run.plan is None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Plan is {run.status}")
        snapshot = Snapshot.model_validate_json(run.snapshot)
        if job_id not in {j.id for j in snapshot.jobs}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not in this plan")
        facts = why(snapshot, Plan.model_validate_json(run.plan), job_id)
        text, source = narrate(facts, "ar" if lang == "ar" else "en")
        return {"facts": facts, "text": text, "source": source}

    def whatif_view(run: WhatIfRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "plan_run_id": run.plan_run_id,
            "status": run.status,
            "created_at": iso(run.created_at),
            "change": json.loads(run.change),
            "result": json.loads(run.result) if run.result else None,
            "error": (
                run.error
                if is_safe_error(run.error)
                else "The what-if could not be computed; see the server log."
                if run.error
                else None
            ),
        }

    @app.post("/api/plans/{run_id}/whatif", status_code=status.HTTP_202_ACCEPTED)
    def start_whatif(
        run_id: str,
        body: WhatIfRequest,
        request: Request,
        session: Db,
        user: Annotated[User, Depends(dispatcher)],
    ) -> dict[str, Any]:
        run = run_of(session, user, run_id)
        if run.status != "done" or run.plan is None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Plan is {run.status}")
        snapshot = Snapshot.model_validate_json(run.snapshot)
        jobs, teams = {j.id for j in snapshot.jobs}, {t.id for t in snapshot.teams}
        needs = {
            "drop": ("job",),
            "assign": ("job", "team"),
            "unavailable": ("team", "start", "end"),
        }
        if body.kind not in needs or any(getattr(body, f) is None for f in needs[body.kind]):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Incomplete what-if")
        if (body.job is not None and body.job not in jobs) or (
            body.team is not None and body.team not in teams
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job or truck")
        if body.start and body.end and (body.start.tzinfo is None or body.end <= body.start):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bad time window")
        change = body.model_dump(mode="json", exclude_none=True)
        question = WhatIfRun(
            company_id=user.company_id,
            plan_run_id=run.id,
            created_by=user.id,
            change=json.dumps(change),
        )
        session.add(question)
        session.commit()
        request.app.state.runner.submit_whatif(question.id, run.snapshot, run.plan, change)
        session.refresh(question)
        return whatif_view(question)

    @app.get("/api/whatif/{whatif_id}")
    def get_whatif(whatif_id: str, user: Me, session: Db) -> dict[str, Any]:
        question = session.get(WhatIfRun, whatif_id)
        if question is None or question.company_id != user.company_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        return whatif_view(question)

    @app.get("/api/steering")
    def steering(user: Me, session: Db) -> dict[str, Any]:
        snapshot = operation_of(session, user.company_id)
        trailers = {r.id: r for r in snapshot.resources if r.kind == "trailer"}
        last = latest_done(session, user.company_id)
        return {
            "version": session.get_one(Operation, user.company_id).version,
            "horizon": snapshot.horizon.model_dump(mode="json"),
            "rules": [rule.model_dump(mode="json") for rule in snapshot.rules],
            "locks": [lock.model_dump(mode="json") for lock in snapshot.locks],
            "latest_plan": last.id if last else None,
            "teams": [
                {
                    "id": t.id,
                    "name": t.name,
                    "depot": snapshot.home_of(t),
                    "tractor_id": t.tractor_id,
                    "equipment": trailers[t.trailer_id].equipment,
                }
                for t in snapshot.teams
            ],
            "jobs": [
                {"id": j.id, "reference": j.reference, "customer": j.customer, "state": j.state}
                for j in snapshot.jobs
            ],
            "sites": [site.model_dump() for site in snapshot.sites],
            "customers": sorted({j.customer for j in snapshot.jobs}),
            "ai": settings.ai_configured,
        }

    def save_checked(session: Session, company_id: str, data: dict[str, Any]) -> Snapshot:
        """Validate the changed snapshot fields and save; 422 with the reason when invalid."""
        snapshot = operation_of(session, company_id)
        try:
            changed = Snapshot.model_validate(dict(snapshot) | data)
        except ValidationError as error:
            reason = error.errors()[0]["msg"].removeprefix("Value error, ")
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, reason) from error
        save_operation(session, company_id, changed)
        return changed

    @app.post("/api/rules")
    def add_rule(
        body: RuleRequest, session: Db, user: Annotated[User, Depends(dispatcher)]
    ) -> dict[str, Any]:
        snapshot = operation_of(session, user.company_id)
        try:
            rule = Rule.model_validate(body.model_dump() | {"id": new_id()})
        except ValidationError as error:
            reason = error.errors()[0]["msg"].removeprefix("Value error, ")
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, reason) from error
        save_checked(session, user.company_id, {"rules": (*snapshot.rules, rule)})
        return rule.model_dump(mode="json")

    @app.delete("/api/rules/{rule_id}")
    def delete_rule(
        rule_id: str, session: Db, user: Annotated[User, Depends(dispatcher)]
    ) -> dict[str, bool]:
        snapshot = operation_of(session, user.company_id)
        rules = tuple(r for r in snapshot.rules if r.id != rule_id)
        if len(rules) == len(snapshot.rules):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
        save_checked(session, user.company_id, {"rules": rules})
        return {"ok": True}

    @app.post("/api/rules/interpret")
    def interpret_rule(
        body: InterpretRequest, session: Db, user: Annotated[User, Depends(dispatcher)]
    ) -> dict[str, Any]:
        """Propose (never apply) a rule from an Arabic or English sentence."""
        snapshot = operation_of(session, user.company_id)
        try:
            return propose_rule(snapshot, body.text)
        except InterpretationError as error:
            return {"status": "error", "explanation": str(error), "rule": None}

    def accept_offers(snapshot: Snapshot, job_ids: set[str]) -> tuple[Job, ...]:
        """Spot loads among ``job_ids`` become commitments: a driver is going for them."""
        return tuple(
            j.model_copy(update={"state": "confirmed"})
            if j.id in job_ids and j.state == "offered"
            else j
            for j in snapshot.jobs
        )

    @app.post("/api/locks")
    def add_lock(
        body: LockRequest, session: Db, user: Annotated[User, Depends(dispatcher)]
    ) -> dict[str, Any]:
        snapshot = operation_of(session, user.company_id)
        locks = tuple(lock for lock in snapshot.locks if lock.job_id != body.job_id)
        lock = AssignmentLock(job_id=body.job_id, team_id=body.team_id)
        jobs = accept_offers(snapshot, {body.job_id})
        save_checked(session, user.company_id, {"locks": (*locks, lock), "jobs": jobs})
        return lock.model_dump(mode="json")

    @app.delete("/api/locks/{job_id}")
    def delete_lock(
        job_id: str, session: Db, user: Annotated[User, Depends(dispatcher)]
    ) -> dict[str, bool]:
        snapshot = operation_of(session, user.company_id)
        locks = tuple(lock for lock in snapshot.locks if lock.job_id != job_id)
        save_checked(session, user.company_id, {"locks": locks})
        return {"ok": True}

    @app.delete("/api/locks")
    def clear_locks(session: Db, user: Annotated[User, Depends(dispatcher)]) -> dict[str, bool]:
        save_checked(session, user.company_id, {"locks": ()})
        return {"ok": True}

    @app.post("/api/locks/freeze")
    def freeze(
        body: FreezeRequest, session: Db, user: Annotated[User, Depends(dispatcher)]
    ) -> dict[str, int]:
        """Freeze every job of a plan whose pickup starts in the next ``hours``."""
        run = run_of(session, user, body.run_id)
        if run.status != "done" or run.plan is None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Plan is {run.status}")
        snapshot = operation_of(session, user.company_id)
        jobs, teams = {j.id for j in snapshot.jobs}, {t.id for t in snapshot.teams}
        until = snapshot.horizon.start + timedelta(hours=body.hours)
        plan = Plan.model_validate_json(run.plan)
        locked = {lock.job_id: lock for lock in snapshot.locks}
        added = 0
        for a in plan.assignments:
            if a.pickup_at < until and a.job_id in jobs and a.team_id in teams:
                added += a.job_id not in locked
                locked[a.job_id] = AssignmentLock(job_id=a.job_id, team_id=a.team_id)
        offered = {j.id for j in snapshot.jobs if j.state == "offered"}
        accepted = len(offered & set(locked))
        changed = {"locks": tuple(locked.values()), "jobs": accept_offers(snapshot, set(locked))}
        save_checked(session, user.company_id, changed)
        return {"frozen": len(locked), "added": added, "accepted": accepted}

    # --- data in: planning window, orders and fleet ------------------------------------

    def save_operation(session: Session, company_id: str, snapshot: Snapshot) -> int:
        # Never store a situation the engine would refuse to plan.
        problems = input_findings(snapshot)
        if problems:
            more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problems[0].message + more)
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
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Start needs a timezone")
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
