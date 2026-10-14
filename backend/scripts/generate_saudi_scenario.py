"""Generate a realistic synthetic Saudi FTL scenario on the real road network.

Usage (from backend/):
  uv run python scripts/generate_saudi_scenario.py --name full --trucks 100 --days 7 --realistic
  uv run python scripts/generate_saudi_scenario.py --name pilot --trucks 40 --days 2 --no-rest-blocks

Network distances come from data/saudi/lanes.csv (OSRM/OpenStreetMap). Demand,
rates, costs and fleet mix are documented assumptions, not customer data. The
lane weights deliberately reproduce the reported pattern of trucks running full
into Riyadh and returning empty. See data/saudi/README.md for sources.
"""

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from freight.domain.models import (
    CostProfile,
    DrivingRules,
    Job,
    Lane,
    Resource,
    Site,
    Snapshot,
    Team,
    Window,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "saudi"

REGION = {
    **dict.fromkeys(["dammam_port", "dammam_ind2", "jubail", "hofuf", "causeway", "batha"], "east"),
    **dict.fromkeys(
        ["riyadh", "riyadh_ind2", "riyadh_dryport", "kharj", "sudair", "buraydah"], "central"
    ),
    **dict.fromkeys(
        ["jeddah_port", "jeddah_ind", "kaec_port", "rabigh", "makkah", "taif", "madinah", "yanbu"],
        "west",
    ),
    **dict.fromkeys(["khamis", "jazan", "najran"], "south"),
    **dict.fromkeys(["hafr", "hail", "tabuk", "sakaka", "arar"], "north"),
}

# Confirmed contract demand: (pickup, delivery, relative weekly weight). Assumption.
CONTRACT_FLOWS = [
    # Imports and industrial output into Riyadh: the dominant head-haul.
    ("dammam_port", "riyadh_dryport", 10),
    ("dammam_port", "riyadh_ind2", 8),
    ("dammam_port", "riyadh", 5),
    ("jubail", "riyadh_ind2", 6),
    ("dammam_ind2", "riyadh", 5),
    ("dammam_port", "kharj", 2),
    ("dammam_port", "buraydah", 2),
    ("jubail", "sudair", 2),
    # Eastern Province short-haul.
    ("dammam_port", "dammam_ind2", 8),
    ("jubail", "dammam_port", 6),
    ("dammam_ind2", "hofuf", 3),
    ("dammam_ind2", "jubail", 2),
    ("causeway", "dammam_ind2", 2),
    # Long-haul and export.
    ("jubail", "jeddah_port", 2),
    ("dammam_ind2", "batha", 2),
    ("dammam_port", "hafr", 1),
    # Riyadh distribution to the regions and thin return flows.
    ("riyadh_ind2", "buraydah", 3),
    ("riyadh_ind2", "hail", 2),
    ("riyadh", "kharj", 2),
    ("riyadh_ind2", "hafr", 1),
    ("riyadh_dryport", "khamis", 2),
    ("riyadh_ind2", "najran", 1),
    ("riyadh", "sakaka", 1),
    ("riyadh_ind2", "jeddah_ind", 2),
    ("riyadh_ind2", "dammam_port", 3),
    ("riyadh", "dammam_ind2", 2),
    ("sudair", "jubail", 1),
    # Western region: Jeddah port imports and distribution.
    ("jeddah_port", "riyadh", 4),
    ("jeddah_port", "jeddah_ind", 7),
    ("jeddah_port", "makkah", 4),
    ("jeddah_port", "madinah", 3),
    ("jeddah_ind", "taif", 2),
    ("jeddah_ind", "khamis", 2),
    ("jeddah_ind", "jazan", 2),
    ("jeddah_ind", "tabuk", 1),
    ("kaec_port", "jeddah_ind", 3),
    ("kaec_port", "riyadh", 2),
    ("rabigh", "jeddah_port", 2),
    ("yanbu", "madinah", 1),
    ("yanbu", "riyadh_ind2", 1),
    ("khamis", "jeddah_ind", 1),
    ("madinah", "jeddah_port", 1),
    ("buraydah", "riyadh_ind2", 1),
    ("hail", "riyadh", 1),
    ("tabuk", "jeddah_ind", 1),
]

# Spot/backhaul opportunities in the weak direction, state="offered". Assumption.
SPOT_FLOWS = [
    ("riyadh_ind2", "dammam_port", 5),
    ("riyadh_dryport", "dammam_ind2", 4),
    ("riyadh", "jubail", 2),
    ("kharj", "dammam_ind2", 2),
    ("buraydah", "dammam_port", 1),
    ("riyadh_ind2", "jeddah_port", 3),
    ("madinah", "jeddah_ind", 2),
    ("makkah", "jeddah_port", 2),
    ("khamis", "riyadh_ind2", 1),
    ("hail", "dammam_ind2", 1),
    ("hofuf", "dammam_port", 2),
    ("batha", "dammam_ind2", 1),
    ("tabuk", "riyadh", 1),
]

DEPOTS = [("dammam_ind2", 0.5, "DMM"), ("riyadh_ind2", 0.3, "RUH"), ("jeddah_ind", 0.2, "JED")]
CUSTOMERS = {
    "port": ["Synthetic Importer A", "Synthetic Importer B", "Synthetic Forwarder C"],
    "industrial": ["Synthetic Petrochem D", "Synthetic Steel E", "Synthetic Building F"],
    "city": ["Synthetic Retail G", "Synthetic FMCG H", "Synthetic Foods I"],
    "border": ["Synthetic Cross-border J"],
}
# Money in halalas (SAR minor units). Assumptions; see data/saudi/README.md.
HEAD_HAUL_PER_KM, BACKHAUL_PER_KM, SHORT_HAUL_PER_KM = 900, 550, 1200
MIN_CHARGE = 70_000
RULES = DrivingRules()
COSTS = CostProfile(
    # 0.72 SAR/km fuel incl. VAT + 0.35 SAR/km tyres/maintenance = 1.07 SAR/km.
    distance_minor_per_km=Decimal("107.00"),
    # SAR 8,000/month fully loaded driver cost over ~260 duty hours.
    duty_minor_per_hour=Decimal("3100.00"),
    exclusions=("Fixed overhead", "Truck depreciation and finance", "Insurance", "Tolls", "Taxes"),
)


def read_network() -> tuple[list[dict[str, str]], dict[tuple[str, str], Lane]]:
    with (DATA / "sites.csv").open(encoding="utf-8") as f:
        sites = list(csv.DictReader(f))
    with (DATA / "lanes.csv").open(encoding="utf-8") as f:
        lanes = {
            (r["from_site_id"], r["to_site_id"]): Lane(
                from_site_id=r["from_site_id"],
                to_site_id=r["to_site_id"],
                distance_m=int(r["distance_m"]),
                duration_minutes=int(r["duration_minutes"]),
                source=r["source"],
            )
            for r in csv.DictReader(f)
        }
    return sites, lanes


def arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--trucks", type=int, default=100)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--loads-per-truck-day", type=float, default=0.7)
    parser.add_argument("--spot-share", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--no-rest-blocks",
        action="store_true",
        help="Omit mid-horizon driver rest and maintenance blocks (current solver allows one duty block per team)",
    )
    parser.add_argument(
        "--realistic",
        action="store_true",
        help="Trucks end where they are, driving-hours rules apply, days off are spent at home",
    )
    return parser


def scenario(*argv: str) -> dict[str, object]:
    """Build a scenario in memory, e.g. scenario("--name", "x", "--trucks", "6")."""
    return build(arguments().parse_args(list(argv)))[0]


def build(
    args: argparse.Namespace,
) -> tuple[dict[str, object], list[Job], dict[tuple[str, str], Lane], list[int]]:
    rng = random.Random(args.seed)
    site_rows, lanes = read_network()
    kinds = {s["id"]: s["kind"] for s in site_rows}
    # Sunday 18 October 2026, 06:00 Riyadh: start of the Saudi working week.
    origin = datetime(2026, 10, 18, 3, tzinfo=UTC)
    horizon = Window(start=origin, end=origin + timedelta(days=args.days))
    available = Window(start=origin, end=horizon.end + timedelta(days=2))

    resources: list[Resource] = []
    teams: list[Team] = []
    depot_counts = [round(args.trucks * share) for _, share, _ in DEPOTS]
    depot_counts[0] += args.trucks - sum(depot_counts)
    for (depot, _, code), count in zip(DEPOTS, depot_counts, strict=True):
        for n in range(1, count + 1):
            number = f"{code}-{n:03}"
            equipment = "flatbed" if rng.random() < 0.3 else "dry_van"
            truck_block: tuple[Window, ...] = ()
            driver_block: tuple[Window, ...] = ()
            if not args.no_rest_blocks:
                # Weekly rest of 24 h for every driver (on a random day), and
                # a 5% chance of a planned 8-24 h workshop visit for the tractor.
                if args.days >= 2:
                    day = rng.randrange(1, args.days)
                    rest_start = origin + timedelta(days=day, hours=rng.choice([0, 6, 12]))
                    driver_block = (Window(start=rest_start, end=rest_start + timedelta(hours=24)),)
                if rng.random() < 0.05:
                    start = origin + timedelta(hours=rng.randrange(6, args.days * 24 - 24))
                    truck_block = (
                        Window(start=start, end=start + timedelta(hours=rng.choice([8, 12, 24]))),
                    )
            resources += [
                Resource(
                    id=f"truck-{number}",
                    name=f"Truck {number}",
                    kind="tractor",
                    site_id=depot,
                    availability=available,
                    unavailable=truck_block,
                    confirmed_at=origin,
                ),
                Resource(
                    id=f"trailer-{number}",
                    name=f"Trailer {number}",
                    kind="trailer",
                    site_id=depot,
                    availability=available,
                    confirmed_at=origin,
                    equipment=equipment,
                    capacity_kg=25_000,
                ),
                Resource(
                    id=f"driver-{number}",
                    name=f"Driver {number}",
                    kind="driver",
                    site_id=depot,
                    availability=available,
                    unavailable=driver_block,
                    confirmed_at=origin,
                ),
            ]
            teams.append(
                Team(
                    id=f"team-{number}",
                    name=f"Team {number}",
                    tractor_id=f"truck-{number}",
                    trailer_id=f"trailer-{number}",
                    driver_id=f"driver-{number}",
                )
            )

    region_weight: Counter[tuple[str, str]] = Counter()
    for a, b, w in CONTRACT_FLOWS:
        region_weight[REGION[a], REGION[b]] += w

    def rate(pickup: str, delivery: str, distance_km: float) -> int:
        a, b = REGION[pickup], REGION[delivery]
        if a == b and distance_km < 250:
            per_km = SHORT_HAUL_PER_KM
        elif region_weight[a, b] >= region_weight[b, a]:
            per_km = HEAD_HAUL_PER_KM
        else:
            per_km = BACKHAUL_PER_KM
        price = max(MIN_CHARGE, distance_km * per_km) * rng.uniform(0.9, 1.1)
        return int(round(price, -2))

    def known_at(index: int, state: str, pickup_start: datetime) -> datetime:
        # Orders arrive 12-72 h ahead, spot offers 6-36 h ahead. A separate random
        # stream keeps every other job attribute identical to earlier versions.
        lead = random.Random(args.seed * 100_003 + index)
        hours = lead.uniform(12, 72) if state == "confirmed" else lead.uniform(6, 36)
        return max(origin, pickup_start - timedelta(hours=hours))

    def make_job(index: int, pickup: str, delivery: str, state: str) -> Job:
        lane = lanes[pickup, delivery]
        km = lane.distance_m / 1000
        kind = kinds[pickup]
        loading = rng.choice([120, 150, 180]) if kind == "port" else rng.choice([60, 75, 90])
        unloading = rng.choice([60, 90, 120])
        day = rng.randrange(args.days)
        hour = rng.choice([6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20])
        pickup_start = origin + timedelta(days=day, hours=hour - 6)
        # A remote pickup cannot start before a truck could arrive from the nearest depot.
        reach = min(lanes[d, pickup].duration_minutes if d != pickup else 0 for d, _, _ in DEPOTS)
        reachable = origin + timedelta(minutes=reach + 60)
        if pickup_start < reachable:
            pickup_start = reachable.replace(minute=0) + timedelta(hours=1)
        pickup_width = rng.choice([4, 6, 8]) if kind == "port" else rng.choice([3, 4, 6])
        # Long trips need breaks and overnight rests before delivery (driving-hours rules).
        transit = RULES.elapsed(lane.duration_minutes)
        earliest = pickup_start + timedelta(minutes=loading + transit)
        delivery_start = earliest.replace(minute=0) + timedelta(hours=1)
        delivery_width = 8 if km < 250 else rng.choice([12, 24])
        flatbed_odds = 0.35 if kind == "industrial" else 0.15 if kind == "port" else 0.08
        return Job(
            id=f"job-{index:04}",
            reference=f"{'SPOT' if state == 'offered' else 'SA'}-{26000 + index}",
            customer=rng.choice(CUSTOMERS[kind]),
            pickup_site_id=pickup,
            delivery_site_id=delivery,
            pickup_window=Window(
                start=pickup_start, end=pickup_start + timedelta(hours=pickup_width)
            ),
            delivery_window=Window(
                start=delivery_start, end=delivery_start + timedelta(hours=delivery_width)
            ),
            loading_minutes=loading,
            unloading_minutes=unloading,
            turnaround_minutes=30,
            equipment="flatbed" if rng.random() < flatbed_odds else "dry_van",
            weight_kg=rng.randrange(8_000, 25_001, 500),
            priority=rng.choices([1, 2, 3], weights=[3, 5, 2])[0],
            state=state,
            revenue_minor=rate(pickup, delivery, km),
            known_at=known_at(index, state, pickup_start),
        )

    confirmed = round(args.trucks * args.days * args.loads_per_truck_day)
    offered = round(confirmed * args.spot_share)
    jobs: list[Job] = []
    for flows, count, state in (
        (CONTRACT_FLOWS, confirmed, "confirmed"),
        (SPOT_FLOWS, offered, "offered"),
    ):
        picks = rng.choices(flows, weights=[w for *_, w in flows], k=count)
        jobs += [make_job(len(jobs) + i + 1, a, b, state) for i, (a, b, _) in enumerate(picks)]
    jobs.sort(key=lambda j: j.pickup_window.start)

    sites = tuple(Site(id=s["id"], name=s["name"], name_ar=s["name_ar"]) for s in site_rows)
    used_sites = {s.id for s in sites}
    snapshot_data = {
        "tenant_id": "demo",
        "scope_id": f"saudi-{args.name}",
        "name": f"Saudi network - {args.trucks} trucks - {args.days} days - synthetic",
        "horizon": horizon.model_dump(mode="json"),
        "sites": [s.model_dump(mode="json") for s in sites],
        "resources": [r.model_dump(mode="json") for r in resources],
        "teams": [t.model_dump(mode="json") for t in teams],
        "jobs": [j.model_dump(mode="json") for j in jobs],
        "lanes": [
            lane.model_dump(mode="json") for k, lane in lanes.items() if set(k) <= used_sites
        ],
        "costs": COSTS.model_dump(mode="json"),
    }
    if args.realistic:
        snapshot_data |= {
            "return_to_start": False,
            "rest_at_home": True,
            "driving_rules": RULES.model_dump(mode="json"),
        }
    return snapshot_data, jobs, lanes, depot_counts


def main() -> None:
    args = arguments().parse_args()
    snapshot_data, jobs, lanes, depot_counts = build(args)
    out = DATA / "scenarios" / args.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "snapshot.json").write_text(
        json.dumps(snapshot_data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    try:
        Snapshot.model_validate(snapshot_data)
        fits = "Yes. Validates against the current Snapshot model."
    except ValidationError as exc:
        reasons = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3])
        fits = f"No. Exceeds the current snapshot limits ({reasons}). Intended for the new engine."

    # Summary: region imbalance, value and empty-return pressure.
    flows: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for job in jobs:
        if job.state == "confirmed":
            flows["out"][REGION[job.pickup_site_id]] += 1
            flows["in"][REGION[job.delivery_site_id]] += 1
    loaded_km = sum(lanes[j.pickup_site_id, j.delivery_site_id].distance_m for j in jobs) / 1000
    by_state = Counter(j.state for j in jobs)
    revenue = Counter()
    for job in jobs:
        revenue[job.state] += job.revenue_minor or 0
    lines = [
        f"# Scenario `{args.name}`",
        "",
        f"Generated by `backend/scripts/generate_saudi_scenario.py --name {args.name} --trucks "
        f"{args.trucks} --days {args.days}{' --no-rest-blocks' if args.no_rest_blocks else ''}{' --realistic' if args.realistic else ''}` "
        f"(seed {args.seed}). **Synthetic demand on the real road network.** Customers, rates "
        "and costs are assumptions; see `data/saudi/README.md`.",
        "",
        "| Item | Value |",
        "| --- | --- |",
        f"| Horizon | {args.days} days from Sun 18 Oct 2026 06:00 Riyadh |",
        f"| Fleet | {args.trucks} fixed teams: "
        + ", ".join(f"{c} at {d}" for (d, _, _), c in zip(DEPOTS, depot_counts, strict=True))
        + " |",
        f"| Confirmed jobs | {by_state['confirmed']} (SAR {revenue['confirmed'] / 100:,.0f} revenue) |",
        f"| Offered spot/backhaul jobs | {by_state['offered']} (SAR {revenue['offered'] / 100:,.0f}) |",
        f"| Loaded km, all jobs | {loaded_km:,.0f} |",
        f"| Driver rest / workshop blocks | {'none' if args.no_rest_blocks else 'weekly 24 h rest per driver; ~5% tractors in workshop'} |",
        "| Operating rules | "
        + (
            "Realistic: trucks end where they are; driving hours (4.5 h then 45 min break, 9 h/day, 11 h rest, 15 h span); days off at home"
            if args.realistic
            else "Classic: every truck returns to its depot by the end; no driving-hours rules"
        )
        + " |",
        f"| Fits current engine | {fits} |",
        "",
        "Confirmed loads by region (out = pickups, in = deliveries). A positive balance means "
        "trucks accumulate there and must leave empty or find backhauls:",
        "",
        "| Region | Out | In | Balance |",
        "| --- | --- | --- | --- |",
    ]
    for region in ("east", "central", "west", "south", "north"):
        o, i = flows["out"][region], flows["in"][region]
        lines.append(f"| {region} | {o} | {i} | {i - o:+} |")
    (out / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
