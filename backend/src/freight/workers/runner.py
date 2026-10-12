"""Durable worker with PostgreSQL claims, renewable leases and fenced writes."""

import argparse
import logging
import signal
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import OperationalError

from freight.db import Revision, Run, session_factory
from freight.domain.models import Snapshot
from freight.planning.baseline import baseline_plan
from freight.planning.comparison import compare_plans
from freight.planning.solver import solve_plan
from freight.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Claim:
    tenant_id: str
    id: str
    attempt: int
    snapshot: Snapshot
    seconds: int
    diagnostic: bool


def claim_next() -> Claim | None:
    with session_factory().begin() as db:
        row = db.scalar(
            select(Run)
            .where(
                or_(
                    Run.state == "queued",
                    and_(Run.state == "running", Run.lease_until < func.now()),
                )
            )
            .order_by(Run.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            return None
        if row.attempt >= 3:
            row.state, row.error = (
                "failed",
                "Worker lease expired three times. Previous results are preserved; start a new run.",
            )
            row.finished_at = db.scalar(select(func.now()))
            return None
        revision = db.get(Revision, (row.tenant_id, row.revision))
        assert revision is not None  # Enforced by a tenant-qualified foreign key.
        row.state, row.attempt = "running", row.attempt + 1
        row.lease_until = db.scalar(
            select(func.now() + timedelta(seconds=get_settings().worker_lease_seconds))
        )
        return Claim(
            row.tenant_id,
            row.id,
            row.attempt,
            Snapshot.model_validate(revision.data),
            row.seconds,
            row.diagnostic,
        )


def fenced_update(claim: Claim, **values: Any) -> bool:
    with session_factory().begin() as db:
        changed = db.execute(
            update(Run)
            .where(
                Run.tenant_id == claim.tenant_id,
                Run.id == claim.id,
                Run.attempt == claim.attempt,
                Run.state == "running",
                Run.lease_until > func.now(),
            )
            .values(**values)
            .returning(Run.id)
        )
        return changed.scalar_one_or_none() is not None


def heartbeat(claim: Claim, stopped: threading.Event) -> None:
    while not stopped.wait(5):
        try:
            renewed = fenced_update(
                claim,
                lease_until=func.now() + timedelta(seconds=get_settings().worker_lease_seconds),
            )
        except OperationalError:
            logger.warning(
                "Lease renewal failed for run %s; the database fence controls result acceptance",
                claim.id,
            )
            continue
        if not renewed:
            return


def execute(claim: Claim) -> None:
    stopped = threading.Event()
    keeper = threading.Thread(target=heartbeat, args=(claim, stopped), daemon=True)
    keeper.start()
    try:
        baseline = baseline_plan(claim.snapshot, seconds=30)
        candidate = solve_plan(
            claim.snapshot, seconds=claim.seconds, diagnostic=claim.diagnostic, hint=baseline
        )
        result = {
            "baseline": baseline.model_dump(mode="json") | {"valid": baseline.valid},
            "candidate": candidate.model_dump(mode="json") | {"valid": candidate.valid},
            "comparison": compare_plans(baseline, candidate),
            "snapshot_hash": claim.snapshot.fingerprint,
        }
        fenced_update(
            claim, state="succeeded", result=result, lease_until=None, finished_at=func.now()
        )
    except Exception:
        logger.exception("Planning attempt failed: %s attempt %s", claim.id, claim.attempt)
        try:
            fenced_update(
                claim,
                state="failed",
                error="Planning failed unexpectedly. Previous results are preserved. Contact the operator with this run ID.",
                lease_until=None,
                finished_at=func.now(),
            )
        except OperationalError:
            logger.warning("Could not record failed run %s; its lease will expire", claim.id)
    finally:
        stopped.set()
        keeper.join(timeout=6)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local freight planning worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Worker ready; waiting for persisted planning runs")
    shutting_down = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: shutting_down.set())
    try:
        while not shutting_down.is_set():
            try:
                claim = claim_next()
            except OperationalError:
                logger.warning("Database unavailable; retrying the durable queue in five seconds")
                if args.once:
                    raise SystemExit(1) from None
                shutting_down.wait(5)
                continue
            if claim:
                execute(claim)
            if args.once:
                return
            if not claim:
                time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Worker stopped; unfinished leases can be recovered")


if __name__ == "__main__":
    main()
