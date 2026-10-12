import csv
import io
from zoneinfo import ZoneInfo

from freight.csv_safety import safe_cell
from freight.domain.models import Plan, Snapshot


def export_plan(snapshot: Snapshot, plan: Plan, revision: int) -> str:
    """A review artifact, never a dispatch instruction or publication command."""
    jobs = {j.id: j for j in snapshot.jobs}
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "mode",
            "revision",
            "snapshot_hash",
            "method",
            "outcome",
            "coverage",
            "job_id",
            "reference",
            "customer",
            "team_id",
            "pickup_at_riyadh",
            "delivery_at_riyadh",
            "released_at_riyadh",
            "assignment_state",
        ]
    )

    common = [
        "SYNTHETIC REVIEW ONLY"
        if snapshot.mode == "demo"
        else "REVIEW ONLY - NOT DISPATCH AUTHORIZATION",
        str(revision),
        snapshot.fingerprint,
        plan.method,
        plan.outcome,
        plan.coverage,
    ]
    assigned = {a.job_id: a for a in plan.assignments}
    for job in jobs.values():
        if job.state != "confirmed":
            continue
        assignment = assigned.get(job.id)
        times = (
            [
                value.astimezone(ZoneInfo("Asia/Riyadh")).isoformat()
                for value in (assignment.pickup_at, assignment.delivery_at, assignment.released_at)
            ]
            if assignment
            else ["", "", ""]
        )
        writer.writerow(
            [
                safe_cell(v)
                for v in [
                    *common,
                    job.id,
                    job.reference,
                    job.customer,
                    assignment.team_id if assignment else "",
                    *times,
                    "assigned" if assignment else "unserved",
                ]
            ]
        )
    return output.getvalue()
