from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from freight.domain.models import AssignmentLock, Snapshot
from freight.sheets import (
    SheetError,
    import_fleet,
    import_jobs,
    read_rows,
    set_window,
    workbook,
)

FULL = Path(__file__).parents[2] / "data" / "saudi" / "scenarios" / "full" / "snapshot.json"


@pytest.fixture(scope="module")
def snapshot() -> Snapshot:
    return Snapshot.model_validate_json(FULL.read_text(encoding="utf-8"))


def csv(text: str) -> bytes:
    return ("﻿" + text).encode("utf-8")  # Excel writes a BOM


JOB_HEADER = (
    "reference,customer,type,pickup_site,delivery_site,pickup_from,pickup_to,"
    "delivery_from,delivery_to,trailer_type,weight_kg,price_sar\n"
)


def test_jobs_round_trip_through_excel(snapshot: Snapshot) -> None:
    rows = read_rows("orders.xlsx", workbook(snapshot, "jobs"), "jobs")
    outcome = import_jobs(snapshot, rows)
    assert outcome.problems == []
    assert outcome.snapshot is not None
    strip = {"known_at"}
    assert [j.model_dump(exclude=strip) for j in outcome.snapshot.jobs] == [
        j.model_dump(exclude=strip) for j in snapshot.jobs
    ]
    assert outcome.summary["kept"] == len(snapshot.jobs)
    assert outcome.summary["added"] == outcome.summary["removed"] == 0


def test_fleet_round_trip_through_excel(snapshot: Snapshot) -> None:
    rows = read_rows("fleet.xlsx", workbook(snapshot, "fleet"), "fleet")
    outcome = import_fleet(snapshot, rows)
    assert outcome.problems == []
    assert outcome.snapshot is not None
    assert outcome.snapshot.teams == snapshot.teams
    assert outcome.snapshot.resources == snapshot.resources


def test_templates_import_cleanly(snapshot: Snapshot) -> None:
    for kind, importer in (("jobs", import_jobs), ("fleet", import_fleet)):
        rows = read_rows("t.xlsx", workbook(snapshot, kind, template=True), kind)  # type: ignore[arg-type]
        outcome = importer(snapshot, rows)  # type: ignore[operator]
        assert outcome.problems == [], kind


def test_csv_with_arabic_sites_and_day_first_dates(snapshot: Snapshot) -> None:
    content = csv(
        JOB_HEADER + "SO-1,Cust,contract,الرياض,jeddah_port,19/10/2026 08:00,19/10/2026 12:00,"
        '2026-10-20 08:00,2026-10-20 20:00,dry van,"22,000",4200\n'
    )
    outcome = import_jobs(snapshot, read_rows("orders.csv", content, "jobs"))
    assert outcome.problems == []
    assert outcome.snapshot is not None
    (job,) = outcome.snapshot.jobs
    assert job.pickup_site_id == "riyadh"
    assert job.pickup_window.start == datetime(2026, 10, 19, 5, 0, tzinfo=UTC)  # 08:00 Riyadh
    assert job.weight_kg == 22_000 and job.revenue_minor == 420_000
    assert job.equipment == "dry_van" and job.state == "confirmed"


def test_every_bad_cell_is_reported_and_nothing_changes(snapshot: Snapshot) -> None:
    content = csv(
        JOB_HEADER + "SO-1,Cust,contract,Atlantis,riyadh,2026-10-19 08:00,2026-10-19 07:00,"
        "2026-10-20 08:00,2026-10-20 20:00,reefer,abc,\n"
        + "SO-1,,spot,riyadh,riyadh,tomorrow,2026-10-19 12:00,2026-10-20 08:00,"
        "2026-10-20 20:00,flatbed,500000,\n"
    )
    outcome = import_jobs(snapshot, read_rows("orders.csv", content, "jobs"))
    assert outcome.snapshot is None
    found = {(p.row, p.column, p.code) for p in outcome.problems}
    assert found == {
        (2, "pickup_site", "unknown_site"),
        (2, "pickup_to", "ends_before_start"),
        (2, "trailer_type", "bad_choice"),
        (2, "weight_kg", "bad_number"),
        (3, "reference", "duplicate"),
        (3, "customer", "required"),
        (3, "pickup_from", "bad_time"),
        (3, "weight_kg", "out_of_range"),
    }


def test_missing_columns_and_wrong_file_type(snapshot: Snapshot) -> None:
    with pytest.raises(SheetError) as missing:
        read_rows("orders.csv", csv("reference,customer\nA,B\n"), "jobs")
    assert missing.value.code == "missing_columns"
    assert "pickup_site" in missing.value.detail
    with pytest.raises(SheetError) as wrong:
        read_rows("orders.pdf", b"%PDF", "jobs")
    assert wrong.value.code == "file_type"


def test_removing_a_job_drops_its_lock(snapshot: Snapshot) -> None:
    job, team = snapshot.jobs[0], snapshot.teams[0]
    locked = Snapshot.model_validate(
        dict(snapshot) | {"locks": (AssignmentLock(job_id=job.id, team_id=team.id),)}
    )
    rows = read_rows("orders.xlsx", workbook(locked, "jobs"), "jobs")
    kept = import_jobs(locked, rows)
    assert kept.snapshot is not None and len(kept.snapshot.locks) == 1
    without_first = [(n, v) for n, v in rows if v["reference"] != job.reference]
    dropped = import_jobs(locked, without_first)
    assert dropped.snapshot is not None and dropped.snapshot.locks == ()
    assert dropped.summary["removed"] == 1 and dropped.summary["locks_dropped"] == 1


def test_fleet_time_off_and_current_site(snapshot: Snapshot) -> None:
    content = csv(
        "truck_id,home_site,current_site,trailer_type,driver_time_off\n"
        "X-1,riyadh,jeddah_port,flatbed,2026-10-21; 2026-10-23 18:00 to 2026-10-24 06:00\n"
    )
    outcome = import_fleet(snapshot, read_rows("fleet.csv", content, "fleet"))
    assert outcome.problems == []
    assert outcome.snapshot is not None
    (team,) = outcome.snapshot.teams
    assert team.home_site_id == "riyadh"
    driver = next(r for r in outcome.snapshot.resources if r.kind == "driver")
    assert driver.site_id == "jeddah_port"
    assert [w.start.hour for w in driver.unavailable] == [21, 15]  # Riyadh midnight, 18:00
    assert driver.unavailable[0].end - driver.unavailable[0].start == timedelta(days=1)


def test_set_window_moves_fleet_availability(snapshot: Snapshot) -> None:
    start = snapshot.horizon.start + timedelta(days=1)
    moved = set_window(snapshot, start, 2)
    assert moved.horizon.end == start + timedelta(days=2)
    assert {r.availability.start for r in moved.resources} == {start}
    assert {r.availability.end for r in moved.resources} == {start + timedelta(days=4)}
