"""Data in: the planning window, the next day, and orders and fleet as Excel/CSV."""

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status

from freight.api.db import Operation
from freight.api.deps import Db, Dispatcher, Me
from freight.api.schemas import RollRequest, WindowRequest
from freight.api.store import iso, latest_done, load, run_of, save, unprocessable
from freight.domain.models import Plan
from freight.rolling import roll_forward
from freight.sheets import (
    Kind,
    SheetError,
    import_fleet,
    import_jobs,
    read_rows,
    set_window,
    workbook,
)

router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/data")
def data_overview(user: Me, session: Db) -> dict[str, Any]:
    snapshot, version = load(session, user.company_id)
    row = session.get_one(Operation, user.company_id)
    horizon = snapshot.horizon
    depots: dict[str, int] = {}
    for team in snapshot.teams:
        depots[snapshot.home_of(team)] = depots.get(snapshot.home_of(team), 0) + 1
    trailers = [r for r in snapshot.resources if r.kind == "trailer"]
    return {
        "version": version,
        "updated_at": iso(row.updated_at),
        "window": {"start": horizon.start.isoformat(), "end": horizon.end.isoformat()},
        "jobs": {
            "contract": sum(j.state == "confirmed" for j in snapshot.jobs),
            "spot": sum(j.state == "offered" for j in snapshot.jobs),
            "later": sum(j.pickup_window.start >= horizon.end for j in snapshot.jobs),
            "expired": sum(
                j.state == "confirmed" and j.pickup_window.end <= horizon.start
                for j in snapshot.jobs
            ),
            "customers": len({j.customer for j in snapshot.jobs}),
        },
        "fleet": {
            "trucks": len(snapshot.teams),
            "depots": depots,
            "dry_van": sum(r.equipment == "dry_van" for r in trailers),
            "flatbed": sum(r.equipment == "flatbed" for r in trailers),
        },
        "sites": [s.model_dump() for s in snapshot.sites],
        "locks": len(snapshot.locks),
        "rules": len(snapshot.rules),
    }


@router.post("/data/roll")
def roll(body: RollRequest, session: Db, user: Dispatcher) -> dict[str, Any]:
    """Start the next planning day from a plan, assuming it was carried out so far."""
    operation, version = load(session, user.company_id)
    run = (
        run_of(session, user, body.run_id) if body.run_id else latest_done(session, user.company_id)
    )
    if run is None or run.plan is None or run.status != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "Run a plan first")
    start = operation.horizon.start + timedelta(hours=body.hours)
    days = max(1, (operation.horizon.end - operation.horizon.start).days)
    try:
        rolled, report = roll_forward(operation, Plan.model_validate_json(run.plan), start, days)
    except ValueError as error:
        raise unprocessable(str(error)) from error
    detail = {
        "from_plan": run.id,
        "executed": report["executed"],
        "missed": [m["ref"] for m in report["missed"]],
    }
    report["version"] = save(
        session, user, rolled, based_on=version, action="window.next_day", detail=detail
    )
    report["window"] = rolled.horizon.model_dump(mode="json")
    return report


@router.post("/data/window")
def change_window(body: WindowRequest, session: Db, user: Dispatcher) -> dict[str, Any]:
    if body.start.tzinfo is None:
        raise unprocessable("Start needs a timezone")
    snapshot, version = load(session, user.company_id)
    moved = set_window(snapshot, body.start, body.days)
    detail = {"start": body.start.isoformat(), "days": body.days}
    return {
        "version": save(session, user, moved, based_on=version, action="window.set", detail=detail)
    }


@router.get("/data/{kind}.xlsx")
def download_sheet(kind: Kind, user: Me, session: Db, template: bool = False) -> Response:
    snapshot, _ = load(session, user.company_id)
    name = ("orders" if kind == "jobs" else "fleet") + ("-template" if template else "")
    return Response(
        workbook(snapshot, kind, template=template),
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
    )


@router.post("/data/{kind}")
def upload_sheet(
    kind: Kind,
    session: Db,
    user: Dispatcher,
    file: Annotated[UploadFile, File()],
    apply: bool = False,
    version: int | None = None,
) -> dict[str, Any]:
    """Check an uploaded sheet; with ``apply`` (and no problems) replace the data.

    A plain (not async) handler: parsing and checking thousands of rows runs in the
    worker thread pool instead of blocking every other request.
    """
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")
    snapshot, current = load(session, user.company_id)
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
        "version": current,
    }
    if apply and outcome.snapshot is not None:
        if version is not None and version != current:
            raise HTTPException(status.HTTP_409_CONFLICT, "The data changed; check again")
        detail = {"file": file.filename, **outcome.summary}
        action = "orders.upload" if kind == "jobs" else "fleet.upload"
        result["version"] = save(
            session, user, outcome.snapshot, based_on=current, action=action, detail=detail
        )
        result["applied"] = True
    return result
