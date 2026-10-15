"""Plans run outside the web process, so the site stays responsive while the engine works."""

import json
import traceback
from concurrent.futures import Executor, Future
from typing import Any

from sqlalchemy.orm import sessionmaker

from freight.api.db import PlanRun, utcnow
from freight.domain.models import Plan, Snapshot
from freight.planning.engine import plan_lns
from freight.planning.lookahead import plan_with_lookahead


def compute_plan(snapshot_json: str, settings: dict[str, Any]) -> tuple[str, str]:
    """Runs in a worker process. Returns (planned snapshot JSON, plan JSON)."""
    snapshot = Snapshot.model_validate_json(snapshot_json)
    seconds = float(settings.get("seconds", 30))
    seed = int(settings.get("seed", 1))
    rounds = settings.get("rounds")
    if settings.get("lookahead"):
        snapshot, plan = plan_with_lookahead(snapshot, seconds=seconds, seed=seed)
    else:
        plan = plan_lns(snapshot, seconds=seconds, seed=seed, rounds=rounds)
    return snapshot.model_dump_json(), plan.model_dump_json()


def summarize(snapshot: Snapshot, plan: Plan) -> dict[str, Any]:
    confirmed = {j.id for j in snapshot.jobs if j.state == "confirmed"}
    offered = {j.id for j in snapshot.jobs if j.state == "offered"}
    served = {a.job_id for a in plan.assignments}
    c = plan.costs
    empty = c.empty_distance_m if c else 0
    loaded = c.loaded_distance_m if c else 0
    return {
        "valid": plan.valid,
        "findings": sorted({f.code for f in plan.findings}),
        "confirmed": len(confirmed),
        "served": len(served & confirmed),
        "offered": len(offered),
        "offers_taken": len(served & offered),
        "empty_share": round(empty / (empty + loaded), 3) if empty + loaded else None,
        "cost_minor": c.total_minor if c else None,
        "revenue_minor": c.revenue_minor if c else None,
        "runtime_s": round(plan.runtime_ms / 1000, 1),
    }


class Runner:
    def __init__(self, executor: Executor, session: sessionmaker) -> None:  # type: ignore[type-arg]
        self.executor = executor
        self.session = session

    def submit(self, run_id: str, snapshot_json: str, settings: dict[str, Any]) -> Future:  # type: ignore[type-arg]
        with self.session.begin() as db:
            db.get_one(PlanRun, run_id).status = "running"
        future = self.executor.submit(compute_plan, snapshot_json, settings)
        future.add_done_callback(lambda done: self._finish(run_id, done))
        return future

    def _finish(self, run_id: str, future: Future) -> None:  # type: ignore[type-arg]
        with self.session.begin() as db:
            run = db.get_one(PlanRun, run_id)
            run.finished_at = utcnow()
            try:
                snapshot_json, plan_json = future.result()
            except Exception:  # the engine failed: record it, never crash the site
                run.status = "failed"
                run.error = traceback.format_exc(limit=3)
                return
            snapshot = Snapshot.model_validate_json(snapshot_json)
            plan = Plan.model_validate_json(plan_json)
            run.snapshot, run.plan = snapshot_json, plan_json
            run.summary = json.dumps(summarize(snapshot, plan))
            run.status = "done"
