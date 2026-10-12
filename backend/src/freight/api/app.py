import hashlib
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import Field, ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from freight import ai, imports
from freight.api.middleware import RequestBoundary
from freight.api.views import ImportView, PlanView, RunView, WorkspaceView
from freight.auth import router as auth_router
from freight.auth import session_cookie
from freight.db import (
    Audit,
    ImportBatch,
    LoginSession,
    MappingProfile,
    Membership,
    Revision,
    RuleProposal,
    Run,
    Tenant,
    session_factory,
)
from freight.domain.models import AssignmentLock, CostProfile, Job, Model, Rule, Snapshot
from freight.exports import export_plan
from freight.services import (
    DEMO_TENANTS,
    remember_request,
    repeat_request,
    revise,
    seed_demo,
    workspace,
)
from freight.settings import get_settings
from freight.validation.validator import input_findings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if get_settings().freight_mode == "demo":
        with session_factory().begin() as db:
            seed_demo(db)
    yield


app = FastAPI(
    title="Freight planning",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if get_settings().freight_mode == "demo" else None,
    redoc_url=None,
)
app.include_router(auth_router)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_settings().allowed_hosts)
if get_settings().freight_mode == "production":
    signing_key = get_settings().session_signing_key
    assert signing_key is not None
    app.add_middleware(
        SessionMiddleware,
        secret_key=signing_key.get_secret_value(),
        session_cookie="__Host-freight_oidc",
        max_age=600,
        same_site="lax",
        https_only=True,
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().freight_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Freight-Request"],
)


@app.middleware("http")
async def local_boundary(request: Request, call_next: Any) -> Response:
    settings = get_settings()
    if settings.freight_mode == "demo" and (
        request.client is None or request.client.host not in ("127.0.0.1", "::1", "testclient")
    ):
        return JSONResponse(
            {"detail": "This synthetic demo accepts loopback connections only"}, 403
        )
    if settings.freight_mode == "production" and request.url.scheme != "https":
        return JSONResponse({"detail": "HTTPS is required"}, 400)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if request.headers.get("x-freight-request") != "1" or (
            origin and origin not in get_settings().freight_allowed_origins
        ):
            return JSONResponse({"detail": "Untrusted request origin"}, 403)
    response: Response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.freight_mode == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


app.add_middleware(RequestBoundary)


@app.exception_handler(ValidationError)
async def domain_error(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        {"detail": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}, 422
    )


@app.exception_handler(RequestValidationError)
async def request_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        {"detail": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}, 422
    )


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    return JSONResponse(
        {
            "detail": "The database is temporarily unavailable. Retry shortly; use the same request identity for pending imports, plans or interpretations."
        },
        503,
    )


def database() -> Iterator[Session]:
    with session_factory()() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


# Commit or roll back before an HTTP success reaches the caller.
Db = Annotated[Session, Depends(database, scope="function")]


def tenant(request: Request, db: Db) -> str:
    token = request.cookies.get(get_settings().cookie_name, "")
    login = db.get(LoginSession, hashlib.sha256(token.encode()).hexdigest()) if token else None
    if login is None or login.expires_at <= datetime.now(UTC):
        raise HTTPException(401, "Your session has expired. Sign in to continue.")
    if get_settings().freight_mode == "production":
        if not login.issuer or not login.subject or login.issuer != get_settings().oidc_issuer:
            raise HTTPException(401, "Sign in to continue")
        member = db.get(Membership, (login.tenant_id, login.issuer, login.subject))
        if member is None or not member.active:
            raise HTTPException(403, "Workspace membership is no longer active")
        if request.method not in ("GET", "HEAD", "OPTIONS") and member.role != "dispatcher":
            raise HTTPException(403, "Your workspace role allows viewing only")
        db.info["actor"] = f"{login.issuer}|{login.subject}"
        db.info["role"] = member.role
    else:
        db.info["actor"] = "local-demo"
        db.info["role"] = "dispatcher"
    return login.tenant_id


TenantId = Annotated[str, Depends(tenant, scope="function")]


class LoginBody(Model):
    tenant_id: str


class VersionBody(Model):
    expected_version: int = Field(ge=1)


class RunBody(VersionBody):
    diagnostic: bool = False
    seconds: int = Field(default=10, ge=1, le=30)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ImportBody(Model):
    entity: imports.Entity
    content: str = Field(max_length=2_000_000)
    source_name: str = Field(default="CSV import", min_length=1, max_length=150)
    mapping: dict[str, str] = {}


class CommitBody(VersionBody):
    lines: list[int] = Field(max_length=500)
    overrides: list[int] = Field(default=[], max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=100)


class ManualRuleBody(VersionBody):
    rule: Rule


class TextRuleBody(VersionBody):
    text: str = Field(min_length=3, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=100)


class LockBody(VersionBody):
    locks: tuple[AssignmentLock, ...]


class CostBody(VersionBody):
    costs: CostProfile


class JobBody(VersionBody):
    job: Job


def run_payload(row: Run, *, detail: bool = True) -> dict[str, Any]:
    return {
        "id": row.id,
        "revision": row.revision,
        "state": row.state,
        "attempt": row.attempt,
        "diagnostic": row.diagnostic,
        "seconds": row.seconds,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "error": row.error,
        "result": row.result if detail else None,
    }


@app.get("/health")
def health(db: Db) -> dict[str, Any]:
    db.execute(select(1))
    stalled = (
        db.scalar(
            select(func.count())
            .select_from(Run)
            .where(
                or_(
                    and_(Run.state == "queued", Run.created_at < func.now() - timedelta(minutes=5)),
                    and_(
                        Run.state == "running", Run.lease_until < func.now() - timedelta(minutes=1)
                    ),
                )
            )
        )
        or 0
    )
    if stalled:
        raise HTTPException(503, "Planning queue is stalled; the worker needs attention")
    return {
        "status": "ok",
        "mode": get_settings().freight_mode,
        "ai_configured": get_settings().ai_configured,
        "publication_enabled": False,
    }


@app.get("/api/demo-workspaces")
def demo_workspaces() -> list[dict[str, str]]:
    if get_settings().freight_mode != "demo":
        raise HTTPException(404, "Demo login is disabled")
    return [{"id": k, "name": v} for k, v in DEMO_TENANTS.items()]


@app.post("/api/session")
def login(body: LoginBody, request: Request, response: Response, db: Db) -> dict[str, str]:
    if get_settings().freight_mode != "demo":
        raise HTTPException(404, "Demo login is disabled; use SSO")
    if body.tenant_id not in DEMO_TENANTS:
        raise HTTPException(404, "Unknown demo workspace")
    old = request.cookies.get(get_settings().cookie_name)
    if old:
        previous = db.get(LoginSession, hashlib.sha256(old.encode()).hexdigest())
        if previous:
            db.delete(previous)
    token = secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            tenant_id=body.tenant_id,
            expires_at=datetime.now(UTC) + timedelta(hours=8),
        )
    )
    session_cookie(response, token)
    return {"tenant_id": body.tenant_id, "name": DEMO_TENANTS[body.tenant_id]}


@app.delete("/api/session")
def logout(request: Request, response: Response, db: Db) -> dict[str, bool]:
    token_hash = hashlib.sha256(
        request.cookies.get(get_settings().cookie_name, "").encode()
    ).hexdigest()
    row = db.get(LoginSession, token_hash)
    if row:
        db.add(
            Audit(
                tenant_id=row.tenant_id,
                actor=f"{row.issuer}|{row.subject}" if row.subject else "local-demo",
                kind="sign_out",
                data={},
            )
        )
        db.delete(row)
    response.delete_cookie(
        get_settings().cookie_name,
        path="/",
        secure=get_settings().freight_mode == "production",
        httponly=True,
        samesite="strict",
    )
    return {"ok": True}


@app.get("/api/workspace", response_model=WorkspaceView)
def get_workspace(tenant_id: TenantId, db: Db) -> dict[str, Any]:
    row = workspace(db, tenant_id)
    owner = db.get(Tenant, tenant_id)
    assert owner is not None
    snapshot = Snapshot.model_validate(row.data)
    return {
        "version": row.version,
        "snapshot": row.data,
        "name": owner.name,
        "role": db.info.get("role", "viewer"),
        "input_findings": [f.model_dump() for f in input_findings(snapshot)],
        "ai_configured": get_settings().ai_configured,
        "ai_model": get_settings().openai_model_rules or None,
    }


@app.put("/api/jobs/{job_id}")
def update_job(job_id: str, body: JobBody, tenant_id: TenantId, db: Db) -> dict[str, int]:
    row = workspace(db, tenant_id, body.expected_version, lock=True)
    if job_id != body.job.id or not any(j["id"] == job_id for j in row.data["jobs"]):
        raise HTTPException(404, "Job not found")
    snapshot = Snapshot.model_validate(
        row.data
        | {
            "jobs": [
                body.job.model_dump(mode="json") if j["id"] == job_id else j
                for j in row.data["jobs"]
            ]
        }
    )
    return {"version": revise(db, row, snapshot, f"Dispatcher corrected job {job_id}")}


@app.put("/api/costs")
def update_costs(body: CostBody, tenant_id: TenantId, db: Db) -> dict[str, int]:
    row = workspace(db, tenant_id, body.expected_version, lock=True)
    snapshot = Snapshot.model_validate(row.data | {"costs": body.costs.model_dump(mode="json")})
    return {"version": revise(db, row, snapshot, "Cost assumptions updated")}


@app.put("/api/locks")
def set_locks(body: LockBody, tenant_id: TenantId, db: Db) -> dict[str, int]:
    row = workspace(db, tenant_id, body.expected_version, lock=True)
    snapshot = Snapshot.model_validate(
        row.data | {"locks": [v.model_dump(mode="json") for v in body.locks]}
    )
    if any(f.code == "invalid_lock" for f in input_findings(snapshot)):
        raise HTTPException(422, "Only confirmed jobs may be locked")
    return {"version": revise(db, row, snapshot, "Assignment locks reviewed")}


@app.get("/api/templates/{entity}")
def csv_template(entity: imports.Entity, tenant_id: TenantId, db: Db) -> PlainTextResponse:
    content = imports.template(Snapshot.model_validate(workspace(db, tenant_id).data), entity)
    return PlainTextResponse(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="current-{entity}.csv"'},
    )


@app.get("/api/mapping-profiles")
def mapping_profiles(tenant_id: TenantId, db: Db) -> list[dict[str, Any]]:
    return [
        {"name": p.name, "entity": p.entity, "mapping": p.mapping}
        for p in db.scalars(select(MappingProfile).where(MappingProfile.tenant_id == tenant_id))
    ]


@app.post("/api/imports", response_model=ImportView)
def preview_import(body: ImportBody, tenant_id: TenantId, db: Db) -> dict[str, Any]:
    row = imports.preview(db, tenant_id, body.entity, body.content, body.source_name, body.mapping)
    return {
        "id": row.id,
        "base_version": row.base_version,
        "entity": row.entity,
        "checksum": row.checksum,
        "mapping": row.mapping,
        "rows": row.rows,
    }


@app.get("/api/imports/{batch_id}", response_model=ImportView)
def get_import(batch_id: str, tenant_id: TenantId, db: Db) -> dict[str, Any]:
    row = db.get(ImportBatch, (tenant_id, batch_id))
    if not row:
        raise HTTPException(404, "Import not found")
    return {
        "id": row.id,
        "base_version": row.base_version,
        "entity": row.entity,
        "checksum": row.checksum,
        "mapping": row.mapping,
        "rows": row.rows,
    }


@app.post("/api/imports/{batch_id}/commit")
def commit_import(batch_id: str, body: CommitBody, tenant_id: TenantId, db: Db) -> dict[str, Any]:
    return imports.commit(
        db,
        tenant_id,
        batch_id,
        body.expected_version,
        body.lines,
        body.overrides,
        body.idempotency_key,
    )


@app.post("/api/runs", status_code=202)
def queue_run(body: RunBody, tenant_id: TenantId, db: Db) -> dict[str, Any]:
    current = workspace(db, tenant_id, lock=True)
    request = body.model_dump() | {"operation": "run"}
    previous = repeat_request(db, tenant_id, body.idempotency_key, request)
    if previous:
        return previous
    if current.version != body.expected_version:
        raise HTTPException(409, "Workspace changed; refresh before planning")
    if (
        db.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.tenant_id == tenant_id, Run.state.in_(["queued", "running"]))
        )
        or 0
    ) >= 2:
        raise HTTPException(429, "Two runs are already active. Wait or cancel one.")
    row = Run(
        tenant_id=tenant_id,
        revision=current.version,
        diagnostic=body.diagnostic,
        seconds=body.seconds,
    )
    db.add(row)
    db.flush()
    result = {"id": row.id, "state": row.state, "revision": row.revision}
    remember_request(db, tenant_id, body.idempotency_key, request, result)
    db.add(Audit(tenant_id=tenant_id, actor=db.info.get("actor"), kind="run_queued", data=result))
    return result


@app.get("/api/runs", response_model=list[RunView])
def list_runs(tenant_id: TenantId, db: Db) -> list[dict[str, Any]]:
    return [
        run_payload(row, detail=False)
        for row in db.scalars(
            select(Run).where(Run.tenant_id == tenant_id).order_by(Run.created_at.desc()).limit(40)
        )
    ]


@app.get("/api/runs/{run_id}", response_model=RunView)
def get_run(run_id: str, tenant_id: TenantId, db: Db) -> dict[str, Any]:
    row = db.get(Run, (tenant_id, run_id))
    if row is None:
        raise HTTPException(404, "Run not found")
    revision = db.get(Revision, (tenant_id, row.revision))
    return run_payload(row) | {"snapshot": revision.data if revision else None}


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, tenant_id: TenantId, db: Db) -> dict[str, Any]:
    row = db.scalar(
        select(Run).where(Run.tenant_id == tenant_id, Run.id == run_id).with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Run not found")
    if row.state in ("queued", "running"):
        row.state, row.lease_until, row.finished_at = "cancelled", None, datetime.now(UTC)
        db.add(
            Audit(
                tenant_id=tenant_id,
                actor=db.info.get("actor"),
                kind="run_cancelled",
                data={"run_id": row.id},
            )
        )
    return run_payload(row, detail=False)


@app.get("/api/runs/{run_id}/export")
def export_run(
    run_id: str, tenant_id: TenantId, db: Db, method: Literal["candidate", "baseline"] = "candidate"
) -> PlainTextResponse:
    row = db.get(Run, (tenant_id, run_id))
    if row is None:
        raise HTTPException(404, "Run not found")
    if row.state != "succeeded" or row.result is None:
        raise HTTPException(409, "This run has no result to export")
    revision = db.get(Revision, (tenant_id, row.revision))
    assert revision is not None
    snapshot = Snapshot.model_validate(revision.data)
    plan = PlanView.model_validate(row.result[method])
    if not plan.valid:
        raise HTTPException(409, "Only independently valid plans can be exported")
    content = export_plan(snapshot, plan, row.revision)
    return PlainTextResponse(
        content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="review-plan-r{row.revision}-{method}.csv"'
        },
    )


@app.post("/api/rules")
def add_rule(body: ManualRuleBody, tenant_id: TenantId, db: Db) -> dict[str, int]:
    row = workspace(db, tenant_id, lock=True)
    existing = next((r for r in row.data["rules"] if r["id"] == body.rule.id), None)
    if existing is not None:
        if existing == body.rule.model_dump(mode="json"):
            return {"version": row.version}
        raise HTTPException(409, "This rule ID already has a different interpretation")
    if row.version != body.expected_version:
        raise HTTPException(409, "Inputs changed. Review the rule against the latest revision.")
    snapshot = Snapshot.model_validate(
        row.data | {"rules": [*row.data["rules"], body.rule.model_dump(mode="json")]}
    )
    return {"version": revise(db, row, snapshot, "Manual operating rule approved")}


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: str, body: VersionBody, tenant_id: TenantId, db: Db) -> dict[str, int]:
    row = workspace(db, tenant_id, body.expected_version, lock=True)
    rules = [r for r in row.data["rules"] if r["id"] != rule_id]
    if len(rules) == len(row.data["rules"]):
        raise HTTPException(404, "Rule not found")
    return {
        "version": revise(
            db, row, Snapshot.model_validate(row.data | {"rules": rules}), "Operating rule removed"
        )
    }


@app.post("/api/rule-proposals")
def propose(body: TextRuleBody, tenant_id: TenantId, db: Db) -> dict[str, Any]:
    row = workspace(db, tenant_id, lock=True)
    request = body.model_dump() | {"operation": "ai_proposal"}
    previous = repeat_request(db, tenant_id, body.idempotency_key, request)
    if previous:
        saved = db.get(RuleProposal, (tenant_id, previous["id"]))
        assert saved is not None
        if saved.state == "pending":
            if saved.created_at < datetime.now(UTC) - timedelta(minutes=2):
                saved.state, saved.result = (
                    "failed",
                    {
                        "error": "The interpretation was interrupted. Submit a new request; no rule was applied."
                    },
                )
                db.commit()
                raise HTTPException(
                    503, saved.result["error"], headers={"X-Freight-Attempt": "complete"}
                )
            raise HTTPException(
                409, "This interpretation is already being processed. Try again shortly."
            )
        if saved.state == "failed":
            raise HTTPException(
                503, saved.result["error"], headers={"X-Freight-Attempt": "complete"}
            )
        return {"id": saved.id, "base_version": saved.base_version, **saved.result}
    if row.version != body.expected_version:
        raise HTTPException(409, "Inputs changed. Review the latest workspace before interpreting.")
    recent = (
        db.scalar(
            select(func.count())
            .select_from(RuleProposal)
            .where(
                RuleProposal.tenant_id == tenant_id,
                RuleProposal.created_at > func.now() - timedelta(minutes=10),
            )
        )
        or 0
    )
    if recent >= 20:
        raise HTTPException(
            429, "Rule interpretation limit reached. Try again later or use manual rules."
        )
    snapshot = Snapshot.model_validate(row.data)
    proposal = RuleProposal(
        tenant_id=tenant_id,
        base_version=body.expected_version,
        text=body.text,
        state="pending",
        result={},
    )
    db.add(proposal)
    db.flush()
    proposal_id = proposal.id
    remember_request(db, tenant_id, body.idempotency_key, request, {"id": proposal_id})
    # Reserve quota under the workspace lock, then release the DB connection
    # before waiting on the provider. Failures count too; retries cannot rebill.
    db.commit()
    try:
        result = ai.propose_rule(snapshot, body.text)
    except ai.InterpretationError as exc:
        proposal.state, proposal.result = "failed", {"error": str(exc)}
        db.commit()
        raise HTTPException(503, str(exc), headers={"X-Freight-Attempt": "complete"}) from exc
    proposal.state, proposal.result = result["status"], result
    return {"id": proposal.id, "base_version": proposal.base_version, **result}


@app.post("/api/rule-proposals/{proposal_id}/approve")
def approve(proposal_id: str, body: VersionBody, tenant_id: TenantId, db: Db) -> dict[str, int]:
    row = workspace(db, tenant_id, lock=True)
    proposal = db.get(RuleProposal, (tenant_id, proposal_id))
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    if proposal.state == "approved" and proposal.result.get("approved_version"):
        return {"version": int(proposal.result["approved_version"])}
    if (
        proposal.state != "proposed"
        or body.expected_version != row.version
        or proposal.base_version != row.version
        or not proposal.result.get("rule")
    ):
        raise HTTPException(
            409, "Only an unapproved proposal for the current revision can be approved"
        )
    snapshot = Snapshot.model_validate(
        row.data | {"rules": [*row.data["rules"], proposal.result["rule"]]}
    )
    proposal.state = "approved"
    version = revise(db, row, snapshot, "OpenAI rule reviewed and approved")
    proposal.result = proposal.result | {"approved_version": version}
    return {"version": version}


@app.get("/api/audit")
def audit_log(tenant_id: TenantId, db: Db) -> list[dict[str, Any]]:
    return [
        {"id": a.id, "kind": a.kind, "actor": a.actor, "data": a.data, "created_at": a.created_at}
        for a in db.scalars(
            select(Audit)
            .where(Audit.tenant_id == tenant_id)
            .order_by(Audit.created_at.desc())
            .limit(50)
        )
    ]
