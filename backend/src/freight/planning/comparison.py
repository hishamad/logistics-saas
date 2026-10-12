from typing import Any

from freight.domain.models import Plan


def compare_plans(baseline: Plan, candidate: Plan) -> dict[str, Any]:
    reasons: list[str] = []
    if baseline.snapshot_hash != candidate.snapshot_hash:
        reasons.append("Inputs differ")
    if not baseline.valid or not candidate.valid:
        reasons.append("Both plans must pass independent validation")
    if {a.job_id for a in baseline.assignments} != {a.job_id for a in candidate.assignments}:
        reasons.append("Served obligations differ")
    if (
        not baseline.costs
        or not candidate.costs
        or not baseline.costs.available
        or not candidate.costs.available
    ):
        reasons.append("Material cost inputs are missing")
    comparable = not reasons
    before = {a.job_id: a for a in baseline.assignments}
    after = {a.job_id: a for a in candidate.assignments}
    changes = sum(
        job_id not in before
        or job_id not in after
        or (before[job_id].team_id, before[job_id].pickup_at)
        != (after[job_id].team_id, after[job_id].pickup_at)
        for job_id in before.keys() | after.keys()
    )
    saving = (
        (baseline.costs.total_minor or 0) - (candidate.costs.total_minor or 0)
        if comparable and baseline.costs and candidate.costs
        else None
    )
    return {
        "comparable": comparable,
        "reasons": reasons,
        "modeled_saving_minor": saving,
        "changed_assignments": changes,
        "label": "Modeled operating cost, not realized savings",
    }
