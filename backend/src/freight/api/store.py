"""Reading and changing a company's data and plans.

Every change to the operation goes through ``save``: it refuses situations the
engine could not plan, refuses to overwrite a newer version (two dispatchers
saving at once), bumps the version and records who did it in the audit trail.
"""

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from freight.api.db import AuditEvent, Operation, PlanRun, User, WhatIfRun, utcnow
from freight.api.runner import is_safe_error
from freight.domain.models import Plan, Snapshot
from freight.rolling import planning_view
from freight.validation.validator import input_findings

RIYADH = ZoneInfo("Asia/Riyadh")


def iso(value: datetime) -> str:
    """ISO time in UTC. SQLite returns stored times without their timezone."""
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def unprocessable(reason: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, reason)


# --- the operation (order book, fleet, rules) -----------------------------------------


def load(session: Session, company_id: str) -> tuple[Snapshot, int]:
    """The company's current situation and its version."""
    row = session.get(Operation, company_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No operation set up yet")
    return Snapshot.model_validate_json(row.snapshot), row.version


def operation_of(session: Session, company_id: str) -> Snapshot:
    return load(session, company_id)[0]


def audit(session: Session, user: User, action: str, detail: dict[str, Any] | None = None) -> None:
    """Record an action; the caller's commit stores it."""
    session.add(
        AuditEvent(
            company_id=user.company_id,
            user_id=user.id,
            action=action,
            detail=json.dumps(detail or {}, ensure_ascii=False, default=str),
        )
    )


def save(
    session: Session,
    user: User,
    snapshot: Snapshot,
    *,
    based_on: int,
    action: str,
    detail: dict[str, Any] | None = None,
) -> int:
    """Store a new version of the operation, if nobody saved another one meanwhile."""
    problems = input_findings(planning_view(snapshot)[0])  # never store an unplannable state
    if problems:
        more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
        raise unprocessable(problems[0].message + more)
    result = session.execute(
        update(Operation)
        .where(Operation.company_id == user.company_id, Operation.version == based_on)
        .values(snapshot=snapshot.model_dump_json(), version=based_on + 1, updated_at=utcnow())
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Someone else changed the data meanwhile. Try again."
        )
    audit(session, user, action, detail)
    session.commit()
    return based_on + 1


def change(
    session: Session,
    user: User,
    fields: dict[str, Any],
    *,
    action: str,
    detail: dict[str, Any] | None = None,
) -> Snapshot:
    """Replace some fields of the current operation, check the result and save it."""
    snapshot, version = load(session, user.company_id)
    try:
        changed = Snapshot.model_validate(dict(snapshot) | fields)
    except ValidationError as error:
        raise unprocessable(error.errors()[0]["msg"].removeprefix("Value error, ")) from error
    save(session, user, changed, based_on=version, action=action, detail=detail)
    return changed


# --- plan runs ------------------------------------------------------------------------


def run_of(session: Session, user: User, run_id: str) -> PlanRun:
    run = session.get(PlanRun, run_id)
    if run is None or run.company_id != user.company_id:  # never reveal other tenants
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return run


def done_plan_of(session: Session, user: User, run_id: str) -> tuple[PlanRun, Snapshot, Plan]:
    run = run_of(session, user, run_id)
    if run.status != "done" or run.plan is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Plan is {run.status}")
    return run, Snapshot.model_validate_json(run.snapshot), Plan.model_validate_json(run.plan)


def latest_done(session: Session, company_id: str) -> PlanRun | None:
    return session.scalar(
        select(PlanRun)
        .where(PlanRun.company_id == company_id, PlanRun.status == "done")
        .order_by(PlanRun.created_at.desc())
        .limit(1)
    )


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


def _error(text: str | None, fallback: str) -> str | None:
    if not text:
        return None
    return text if is_safe_error(text) else fallback


def run_view(run: PlanRun, by: str | None = None) -> dict[str, Any]:
    return {
        "id": run.id,
        "created_by": by,
        "status": run.status,
        "created_at": iso(run.created_at),
        "finished_at": iso(run.finished_at) if run.finished_at else None,
        "settings": json.loads(run.settings),
        "summary": json.loads(run.summary) if run.summary else None,
        "error": _error(run.error, "The planning engine failed; see the server log."),
    }


def whatif_view(run: WhatIfRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "plan_run_id": run.plan_run_id,
        "status": run.status,
        "created_at": iso(run.created_at),
        "change": json.loads(run.change),
        "result": json.loads(run.result) if run.result else None,
        "error": _error(run.error, "The what-if could not be computed; see the server log."),
    }
