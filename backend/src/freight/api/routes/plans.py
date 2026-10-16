"""Plans: run the engine, read the board, explain it, ask what if, hand it over."""

import json
from datetime import UTC
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from freight.api.db import Operation, PlanRun, User, WhatIfRun, utcnow
from freight.api.deps import Db, Dispatcher, Me
from freight.api.runner import INPUT_PROBLEMS, compute_whatif
from freight.api.schemas import PlanRequest, WhatIfRequest
from freight.api.store import (
    RIYADH,
    audit,
    done_plan_of,
    iso,
    latest_done,
    operation_of,
    previous_done,
    run_of,
    run_view,
    unprocessable,
    whatif_view,
)
from freight.board import board_data
from freight.domain.models import Plan, Snapshot
from freight.explain import WhatIfRefused, narrate, why
from freight.handover import export_workbook, plan_changes
from freight.planning.engine import routes_of
from freight.rolling import planning_view

router = APIRouter(prefix="/api")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# What a moved job costs in a stable re-plan (halalas): SAR 300.
CHANGE_PENALTY_MINOR = 30_000


@router.get("/operation")
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


def with_previous(snapshot: Snapshot, plan: Plan) -> Snapshot:
    jobs = {j.id for j in snapshot.jobs}
    teams = {t.id for t in snapshot.teams}
    previous = {
        a.job_id: a.team_id for a in plan.assignments if a.job_id in jobs and a.team_id in teams
    }
    return snapshot.model_copy(
        update={"previous": previous, "change_penalty_minor": CHANGE_PENALTY_MINOR}
    )


@router.post("/plans", status_code=status.HTTP_202_ACCEPTED)
def start_plan(
    body: PlanRequest, request: Request, session: Db, user: Dispatcher
) -> dict[str, Any]:
    # Orders whose pickup starts after the window wait in the order book.
    snapshot, _ = planning_view(operation_of(session, user.company_id))
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
    session.flush()
    audit(session, user, "plan.run", {"run": run.id, "seconds": body.seconds})
    session.commit()
    request.app.state.runner.submit(run.id, run.snapshot, body.model_dump(), initial)
    session.refresh(run)
    return run_view(run)


@router.get("/plans")
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


@router.get("/plans/{run_id}")
def get_plan(run_id: str, user: Me, session: Db) -> dict[str, Any]:
    return run_view(run_of(session, user, run_id))


@router.get("/plans/{run_id}/board")
def get_board(run_id: str, user: Me, session: Db) -> dict[str, object]:
    _, snapshot, plan = done_plan_of(session, user, run_id)
    return board_data(snapshot, plan)


def changes_between(
    session: Session, user: User, run_id: str, against: str | None
) -> tuple[dict[str, Any] | None, PlanRun | None]:
    run, snapshot, plan = done_plan_of(session, user, run_id)
    other = run_of(session, user, against) if against else previous_done(session, run)
    if other is None:
        return None, None
    _, before_snapshot, before = done_plan_of(session, user, other.id)
    return plan_changes(snapshot, plan, before_snapshot, before), other


@router.get("/plans/{run_id}/changes")
def get_changes(run_id: str, user: Me, session: Db, against: str | None = None) -> dict[str, Any]:
    """Changes since ``against`` (default: the plan before this one)."""
    changes, other = changes_between(session, user, run_id, against)
    if other is None:
        return {"against": None, "changes": None}
    return {"against": {"id": other.id, "created_at": iso(other.created_at)}, "changes": changes}


@router.get("/plans/{run_id}/export.xlsx")
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


@router.get("/plans/{run_id}/why/{job_id}")
def explain_job(
    run_id: str, job_id: str, user: Me, session: Db, lang: str = "en"
) -> dict[str, Any]:
    _, snapshot, plan = done_plan_of(session, user, run_id)
    if job_id not in {j.id for j in snapshot.jobs}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not in this plan")
    facts = why(snapshot, plan, job_id)
    text, source = narrate(facts, "ar" if lang == "ar" else "en")
    return {"facts": facts, "text": text, "source": source}


NEEDS = {"drop": ("job",), "assign": ("job", "team"), "unavailable": ("team", "start", "end")}


@router.post("/plans/{run_id}/whatif", status_code=status.HTTP_202_ACCEPTED)
def start_whatif(
    run_id: str, body: WhatIfRequest, request: Request, session: Db, user: Dispatcher
) -> dict[str, Any]:
    run, snapshot, _ = done_plan_of(session, user, run_id)
    jobs, teams = {j.id for j in snapshot.jobs}, {t.id for t in snapshot.teams}
    if body.kind not in NEEDS or any(getattr(body, f) is None for f in NEEDS[body.kind]):
        raise unprocessable("Incomplete what-if")
    if (body.job is not None and body.job not in jobs) or (
        body.team is not None and body.team not in teams
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown job or truck")
    if body.start and body.end and (body.start.tzinfo is None or body.end <= body.start):
        raise unprocessable("Bad time window")
    change = body.model_dump(mode="json", exclude_none=True, exclude={"method"})
    question = WhatIfRun(
        company_id=user.company_id,
        plan_run_id=run.id,
        created_by=user.id,
        change=json.dumps(change | {"method": body.method}),
    )
    session.add(question)
    session.flush()
    audit(session, user, "plan.whatif", change | {"method": body.method})
    if body.method == "repair":
        # Instant and exact for this plan: answer within the request.
        try:
            question.result = compute_whatif(run.snapshot, run.plan or "", change, "repair")
            question.status = "done"
        except WhatIfRefused as refused:
            question.status, question.error = "failed", INPUT_PROBLEMS + str(refused)
        question.finished_at = utcnow()
        session.commit()
    else:
        session.commit()
        request.app.state.runner.submit_whatif(question.id, run.snapshot, run.plan, change)
    session.refresh(question)
    return whatif_view(question)


@router.get("/whatif/{whatif_id}")
def get_whatif(whatif_id: str, user: Me, session: Db) -> dict[str, Any]:
    question = session.get(WhatIfRun, whatif_id)
    if question is None or question.company_id != user.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return whatif_view(question)
