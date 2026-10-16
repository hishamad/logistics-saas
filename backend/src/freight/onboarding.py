"""Setting up a real carrier: the Saudi road network, default policies, its own fleet.

The network (sites and OSRM road lanes) ships with the product in data/saudi.
Cost rates and driving rules below are documented assumptions to confirm with
each carrier (see data/saudi/README.md) before trusting money figures.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from freight.domain.models import (
    CostProfile,
    DrivingRules,
    Lane,
    Resource,
    Site,
    Snapshot,
    Team,
    Window,
)
from freight.sheets import Outcome, import_fleet, import_jobs, read_rows

NETWORK = Path(__file__).resolve().parents[3] / "data" / "saudi"

DEFAULT_RULES = DrivingRules()
DEFAULT_COSTS = CostProfile(
    # 0.72 SAR/km fuel incl. VAT + 0.35 SAR/km tyres/maintenance = 1.07 SAR/km.
    distance_minor_per_km=Decimal("107.00"),
    # SAR 8,000/month fully loaded driver cost over ~260 duty hours.
    duty_minor_per_hour=Decimal("3100.00"),
    exclusions=("Fixed overhead", "Truck depreciation and finance", "Insurance", "Tolls", "Taxes"),
)


def saudi_network(folder: Path = NETWORK) -> tuple[tuple[Site, ...], tuple[Lane, ...]]:
    with (folder / "sites.csv").open(encoding="utf-8") as f:
        sites = tuple(
            Site(id=r["id"], name=r["name"], name_ar=r.get("name_ar", ""))
            for r in csv.DictReader(f)
        )
    with (folder / "lanes.csv").open(encoding="utf-8") as f:
        lanes = tuple(
            Lane(
                from_site_id=r["from_site_id"],
                to_site_id=r["to_site_id"],
                distance_m=int(r["distance_m"]),
                duration_minutes=int(r["duration_minutes"]),
                source=r["source"],
            )
            for r in csv.DictReader(f)
        )
    return sites, lanes


class OnboardingError(ValueError):
    def __init__(self, what: str, outcome: Outcome | None = None, detail: str = "") -> None:
        problems = outcome.problems[:10] if outcome else []
        lines = [
            f"row {p.row}, {p.column or '-'}: {p.code} {p.value} {p.detail}".strip()
            for p in problems
        ]
        super().__init__(f"{what}: {detail}" + ("\n  " + "\n  ".join(lines) if lines else ""))


def new_operation(
    company_id: str,
    name: str,
    fleet_file: tuple[str, bytes],
    start: datetime,
    days: int = 2,
    orders_file: tuple[str, bytes] | None = None,
) -> tuple[Snapshot, dict[str, Any]]:
    """A carrier's first operation: the network, default policies, its fleet and orders.

    Files are (filename, content) of .xlsx or .csv in the product's own templates.
    """
    sites, lanes = saudi_network()
    horizon = Window(start=start, end=start + timedelta(days=days))
    # A placeholder truck satisfies the "at least one team" check until the fleet loads.
    home = sites[0].id
    window = Window(start=start, end=horizon.end)
    placeholder = (
        Resource(
            id="p-t",
            name="p",
            kind="tractor",
            site_id=home,
            availability=window,
            confirmed_at=start,
        ),
        Resource(
            id="p-r",
            name="p",
            kind="trailer",
            site_id=home,
            availability=window,
            confirmed_at=start,
            equipment="dry_van",
            capacity_kg=1,
        ),
        Resource(
            id="p-d", name="p", kind="driver", site_id=home, availability=window, confirmed_at=start
        ),
    )
    base = Snapshot(
        tenant_id=company_id,
        scope_id="operation",
        name=name,
        mode="shadow",
        horizon=horizon,
        sites=sites,
        lanes=lanes,
        resources=placeholder,
        teams=(Team(id="p", name="p", tractor_id="p-t", trailer_id="p-r", driver_id="p-d"),),
        jobs=(),
        costs=DEFAULT_COSTS,
        driving_rules=DEFAULT_RULES,
        return_to_start=False,
        rest_at_home=True,
    )
    fleet = import_fleet(base, read_rows(*fleet_file, "fleet"))
    if fleet.snapshot is None:
        raise OnboardingError("The fleet file has problems", fleet)
    snapshot, summary = fleet.snapshot, {"trucks": fleet.summary["trucks"], "orders": 0}
    if orders_file is not None:
        orders = import_jobs(snapshot, read_rows(*orders_file, "jobs"))
        if orders.snapshot is None:
            raise OnboardingError("The orders file has problems", orders)
        snapshot, summary["orders"] = orders.snapshot, orders.summary["rows"]
    return snapshot, summary
