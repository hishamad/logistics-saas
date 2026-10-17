"""Steering: rules (by form or proposed from a sentence) and frozen jobs."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from freight.ai import InterpretationError, propose_rule
from freight.api.db import Operation, new_id
from freight.api.deps import Db, Dispatcher, Me
from freight.api.schemas import FreezeRequest, InterpretRequest, LockRequest, RuleRequest
from freight.api.store import change, done_plan_of, latest_done, operation_of, unprocessable
from freight.domain.models import AssignmentLock, Job, Rule, Snapshot
from freight.settings import get_settings

router = APIRouter(prefix="/api")


@router.get("/steering")
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
        "ai": get_settings().ai_configured,
    }


@router.post("/rules")
def add_rule(body: RuleRequest, session: Db, user: Dispatcher) -> dict[str, Any]:
    snapshot = operation_of(session, user.company_id)
    try:
        rule = Rule.model_validate(body.model_dump() | {"id": new_id()})
    except ValidationError as error:
        raise unprocessable(error.errors()[0]["msg"].removeprefix("Value error, ")) from error
    detail = {"kind": rule.kind, "text": rule.source_text}
    change(session, user, {"rules": (*snapshot.rules, rule)}, action="rule.add", detail=detail)
    return rule.model_dump(mode="json")


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, session: Db, user: Dispatcher) -> dict[str, bool]:
    snapshot = operation_of(session, user.company_id)
    removed = [r for r in snapshot.rules if r.id == rule_id]
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    rules = tuple(r for r in snapshot.rules if r.id != rule_id)
    detail = {"kind": removed[0].kind, "text": removed[0].source_text}
    change(session, user, {"rules": rules}, action="rule.remove", detail=detail)
    return {"ok": True}


@router.post("/rules/interpret")
def interpret_rule(body: InterpretRequest, session: Db, user: Dispatcher) -> dict[str, Any]:
    """Propose (never apply) a rule from an Arabic or English sentence."""
    snapshot = operation_of(session, user.company_id)
    try:
        return propose_rule(snapshot, body.text, body.lang)
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


def _reference(snapshot: Snapshot, job_id: str) -> str:
    return next((j.reference for j in snapshot.jobs if j.id == job_id), job_id)


@router.post("/locks")
def add_lock(body: LockRequest, session: Db, user: Dispatcher) -> dict[str, Any]:
    snapshot = operation_of(session, user.company_id)
    locks = tuple(lock for lock in snapshot.locks if lock.job_id != body.job_id)
    lock = AssignmentLock(job_id=body.job_id, team_id=body.team_id)
    fields = {"locks": (*locks, lock), "jobs": accept_offers(snapshot, {body.job_id})}
    detail = {"job": _reference(snapshot, body.job_id), "truck": body.team_id}
    change(session, user, fields, action="lock.add", detail=detail)
    return lock.model_dump(mode="json")


@router.delete("/locks/{job_id}")
def delete_lock(job_id: str, session: Db, user: Dispatcher) -> dict[str, bool]:
    snapshot = operation_of(session, user.company_id)
    locks = tuple(lock for lock in snapshot.locks if lock.job_id != job_id)
    detail = {"job": _reference(snapshot, job_id)}
    change(session, user, {"locks": locks}, action="lock.remove", detail=detail)
    return {"ok": True}


@router.delete("/locks")
def clear_locks(session: Db, user: Dispatcher) -> dict[str, bool]:
    count = len(operation_of(session, user.company_id).locks)
    change(session, user, {"locks": ()}, action="lock.clear", detail={"count": count})
    return {"ok": True}


@router.post("/locks/freeze")
def freeze(body: FreezeRequest, session: Db, user: Dispatcher) -> dict[str, int]:
    """Freeze every job of a plan whose pickup starts in the next ``hours``."""
    _, _, plan = done_plan_of(session, user, body.run_id)
    snapshot = operation_of(session, user.company_id)
    jobs, teams = {j.id for j in snapshot.jobs}, {t.id for t in snapshot.teams}
    until = snapshot.horizon.start + timedelta(hours=body.hours)
    locked = {lock.job_id: lock for lock in snapshot.locks}
    added = 0
    for a in plan.assignments:
        if a.pickup_at < until and a.job_id in jobs and a.team_id in teams:
            added += a.job_id not in locked
            locked[a.job_id] = AssignmentLock(job_id=a.job_id, team_id=a.team_id)
    offered = {j.id for j in snapshot.jobs if j.state == "offered"}
    accepted = len(offered & set(locked))
    fields = {"locks": tuple(locked.values()), "jobs": accept_offers(snapshot, set(locked))}
    detail = {"hours": body.hours, "added": added, "accepted": accepted}
    change(session, user, fields, action="lock.freeze", detail=detail)
    return {"frozen": len(locked), "added": added, "accepted": accepted}
