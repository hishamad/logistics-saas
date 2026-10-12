import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from freight.db import Audit, Idempotency, Revision, Tenant, Workspace
from freight.domain.models import Snapshot
from freight.fixtures import demo_snapshot

DEMO_TENANTS = {"eastern-demo": "Eastern Freight · Demo", "western-demo": "Western Freight · Demo"}


def seed_demo(db: Session) -> None:
    # Multiple API processes may start together against an empty database.
    db.execute(text("SELECT pg_advisory_xact_lock(481551390)"))
    for tenant_id, name in DEMO_TENANTS.items():
        if db.get(Tenant, tenant_id) is not None:
            continue
        snapshot = demo_snapshot(tenant_id=tenant_id)
        db.add(Tenant(id=tenant_id, name=name))
        db.flush()
        db.add(Workspace(tenant_id=tenant_id, version=1, data=snapshot.model_dump(mode="json")))
        db.add(
            Revision(
                tenant_id=tenant_id,
                version=1,
                data=snapshot.model_dump(mode="json"),
                fingerprint=snapshot.fingerprint,
                reason="Synthetic demo seeded",
            )
        )


def workspace(
    db: Session, tenant_id: str, expected: int | None = None, *, lock: bool = False
) -> Workspace:
    query = select(Workspace).where(Workspace.tenant_id == tenant_id)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "Workspace not found")
    if expected is not None and expected != row.version:
        raise HTTPException(
            409, "The workspace changed. Refresh and review the new revision before saving."
        )
    return row


def revise(db: Session, row: Workspace, snapshot: Snapshot, reason: str) -> int:
    if snapshot.tenant_id != row.tenant_id:
        raise HTTPException(422, "Snapshot tenant mismatch")
    data = snapshot.model_dump(mode="json")
    row.version += 1
    row.data = data
    db.add(
        Revision(
            tenant_id=row.tenant_id,
            version=row.version,
            data=data,
            fingerprint=snapshot.fingerprint,
            reason=reason,
        )
    )
    db.add(
        Audit(
            tenant_id=row.tenant_id,
            kind="workspace_revised",
            actor=db.info.get("actor"),
            data={"revision": row.version, "reason": reason, "fingerprint": snapshot.fingerprint},
        )
    )
    return row.version


def request_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def repeat_request(db: Session, tenant_id: str, key: str, body: Any) -> dict[str, Any] | None:
    existing = db.get(Idempotency, (tenant_id, key))
    if existing:
        if existing.request_hash != request_hash(body):
            raise HTTPException(409, "This idempotency key belongs to a different request")
        return existing.result
    return None


def remember_request(
    db: Session, tenant_id: str, key: str, body: Any, result: dict[str, Any]
) -> None:
    db.add(
        Idempotency(tenant_id=tenant_id, key=key, request_hash=request_hash(body), result=result)
    )
