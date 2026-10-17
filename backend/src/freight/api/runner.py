"""Plans run outside the web process, so the site stays responsive while the engine works."""

import json
import traceback
from concurrent.futures import Executor, Future
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from freight.api.db import PlanRun, WhatIfRun, utcnow
from freight.domain.models import Finding, Plan, Snapshot
from freight.explain import WhatIfImpossible, WhatIfRefused, narrate, what_if
from freight.planning.engine import plan_lns
from freight.planning.lookahead import plan_with_lookahead
from freight.rolling import release_impossible_locks


def compute_plan(
    snapshot_json: str, settings: dict[str, Any], initial: dict[str, list[str]] | None = None
) -> tuple[str, str]:
    """Runs in a worker process. Returns (planned snapshot JSON, plan JSON).

    ``initial`` (team -> job ids) continues from an earlier plan instead of starting empty."""
    snapshot, released = release_impossible_locks(Snapshot.model_validate_json(snapshot_json))
    seconds = float(settings.get("seconds", 30))
    seed = int(settings.get("seed", 1))
    rounds = settings.get("rounds")
    if settings.get("lookahead"):
        snapshot, plan = plan_with_lookahead(snapshot, seconds=seconds, seed=seed)
    else:
        plan = plan_lns(snapshot, seconds=seconds, seed=seed, rounds=rounds, initial=initial)
    if released:
        # Recorded on the plan so the dispatcher sees which freezes could not be kept.
        notes = tuple(
            Finding(
                code="lock_released",
                message="This frozen job is no longer possible on its truck; the freeze was released.",
                entity_ids=(job_id,),
            )
            for job_id in released
        )
        plan = plan.model_copy(update={"notes": notes})
    return snapshot.model_dump_json(), plan.model_dump_json()


# Errors starting with this are safe to show: they describe the user's own data.
INPUT_PROBLEMS = "The engine refused these inputs: "

INTERRUPTED = "Stopped: the server restarted or the run took far too long. Run it again."


def is_safe_error(error: str | None) -> bool:
    """Errors that describe the user's own data or situation, not server internals."""
    return bool(error) and (error.startswith(INPUT_PROBLEMS) or error == INTERRUPTED)  # type: ignore[union-attr]


# A run still unfinished this long after its start can no longer finish (its process is
# gone): a plan stops after its search time; a what-if re-plan takes well under this.
PLAN_GRACE = timedelta(minutes=3)
WHATIF_LIMIT = timedelta(minutes=10)


def fail_interrupted(session: sessionmaker) -> int:  # type: ignore[type-arg]
    """Fail runs that are unfinished long past the time they could take.

    Judged by age, not by which process asks: a second server starting on the same
    database (a restart overlap, a double start) must not fail runs that are alive.
    """
    now = utcnow()
    count = 0
    with session.begin() as db:
        for table in (PlanRun, WhatIfRun):
            for run in db.scalars(select(table).where(table.status.in_(("queued", "running")))):
                started = run.created_at.replace(tzinfo=run.created_at.tzinfo or UTC)
                if table is PlanRun:
                    seconds = float(json.loads(run.settings).get("seconds", 300))
                    deadline = started + timedelta(seconds=seconds) + PLAN_GRACE
                else:
                    deadline = started + WHATIF_LIMIT
                if now > deadline:
                    run.status, run.error, run.finished_at = "failed", INTERRUPTED, now
                    count += 1
    return count


# Effort per what-if re-plan. Two re-plans of a 100-truck week take about 20 s.
WHATIF_ROUNDS = 800


def compute_whatif(
    snapshot_json: str, plan_json: str, change: dict[str, Any], method: str = "replan"
) -> str:
    """Facts and their text in both languages (JSON); a re-plan runs in a worker process."""
    snapshot = Snapshot.model_validate_json(snapshot_json)
    plan = Plan.model_validate_json(plan_json)
    try:
        facts, _, _ = what_if(
            snapshot,
            plan,
            change,
            method="repair" if method == "repair" else "replan",
            rounds=WHATIF_ROUNDS,
        )
    except WhatIfImpossible as impossible:
        return json.dumps(
            {
                "impossible": True,
                "facts": None,
                "source": "engine",
                "text": {"en": impossible.english, "ar": impossible.arabic},
            },
            ensure_ascii=False,
        )
    texts = {"en": narrate(facts, "en"), "ar": narrate(facts, "ar")}
    return json.dumps(
        {
            "facts": facts,
            "text": {language: text for language, (text, _) in texts.items()},
            "source": texts["en"][1],
        },
        ensure_ascii=False,
    )


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
        "released_locks": [
            next((j.reference for j in snapshot.jobs if j.id == job_id), job_id)
            for note in plan.notes
            if note.code == "lock_released"
            for job_id in note.entity_ids
        ],
        # Jobs on a different truck than in the previous plan (instructions to re-send).
        "changed": sum(
            1
            for a in plan.assignments
            if a.job_id in snapshot.previous and snapshot.previous[a.job_id] != a.team_id
        )
        if snapshot.previous
        else None,
    }


class Runner:
    def __init__(self, executor: Executor, session: sessionmaker) -> None:  # type: ignore[type-arg]
        self.executor = executor
        self.session = session

    def submit(
        self,
        run_id: str,
        snapshot_json: str,
        settings: dict[str, Any],
        initial: dict[str, list[str]] | None = None,
    ) -> Future:  # type: ignore[type-arg]
        with self.session.begin() as db:
            db.get_one(PlanRun, run_id).status = "running"
        future = self.executor.submit(compute_plan, snapshot_json, settings, initial)
        future.add_done_callback(lambda done: self._finish(run_id, done))
        return future

    def submit_whatif(
        self, run_id: str, snapshot_json: str, plan_json: str, change: dict[str, Any]
    ) -> Future:  # type: ignore[type-arg]
        with self.session.begin() as db:
            db.get_one(WhatIfRun, run_id).status = "running"
        future = self.executor.submit(compute_whatif, snapshot_json, plan_json, change)
        future.add_done_callback(lambda done: self._finish_whatif(run_id, done))
        return future

    def _finish_whatif(self, run_id: str, future: Future) -> None:  # type: ignore[type-arg]
        with self.session.begin() as db:
            run = db.get_one(WhatIfRun, run_id)
            run.finished_at = utcnow()
            try:
                run.result = future.result()
                run.status = "done"
            except WhatIfRefused as refused:
                run.status = "failed"
                run.error = INPUT_PROBLEMS + str(refused)
            except Exception:
                run.status = "failed"
                run.error = traceback.format_exc(limit=3)

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
            if plan.outcome == "model_invalid":  # the engine refused the inputs
                run.status = "failed"
                run.error = INPUT_PROBLEMS + "; ".join(f.message for f in plan.findings[:3])
                return
            run.snapshot, run.plan = snapshot_json, plan_json
            run.summary = json.dumps(summarize(snapshot, plan))
            run.status = "done"
