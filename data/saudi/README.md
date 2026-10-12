# Saudi reference data

Researched 12 October 2026. Real where sourced; every assumption is labelled. Not customer data.

## Files

| File | Content | Origin |
| --- | --- | --- |
| `sites.csv` | 28 freight nodes: ports, industrial cities, border crossings, major cities (EN/AR names, approximate coordinates) | Coordinates approximate (±few km); `snapped_road_m` is the OSRM snap distance (all < 3 km) |
| `lanes.csv` | 756 directed lanes (from, to, distance, duration, source) | Distance: [OSRM](https://project-osrm.org/) on OpenStreetMap roads (car profile). Truck duration = car duration × 1.3 (**assumption**) |

Regenerate with `scripts/build_saudi_lanes.py` (see its docstring). Spot checks: Dammam port→Riyadh 431 km, Riyadh→Jeddah 945 km, Jeddah→Jazan 698 km, Riyadh→Tabuk 1,350 km.

The OSRM demo server is car-only and has no weight or height restrictions. Before a pilot, self-host OSRM or GraphHopper with a truck profile on the [Geofabrik](https://download.geofabrik.de/asia/gcc-states.html) GCC extract.

## Scenarios

`scenarios/<name>/` is created by `backend/scripts/generate_saudi_scenario.py`. Each scenario contains a full `snapshot.json` and its own README with region-imbalance statistics.

| Scenario | Fleet | Horizon | Jobs | Current engine |
| --- | --- | --- | --- | --- |
| `pilot` | 40 teams (Dammam 20, Riyadh 12, Jeddah 8) | 48 h | 56 confirmed, 14 offered | Runs today |
| `full` | 100 teams (Dammam 50, Riyadh 30, Jeddah 20) | 7 days | 490 confirmed, 122 offered spot/backhaul; weekly 24 h driver rest | Too large (60 teams / 200 jobs cap): target for the new engine |

The scenarios use fictional customers. The lane weights reproduce "full into Riyadh, empty back": in the full scenario the East ships 143 more loads than it receives and Central receives 137 more. Rates are SAR 9/km head-haul, 5.5/km backhaul and 12/km short-haul, with a SAR 700 minimum. These are **assumptions** calibrated to the single Dammam→Riyadh data point below.

## Cost inputs

| Input | Value | Source / status |
| --- | --- | --- |
| Diesel | SAR 1.79/L before 15% VAT (2026; SAR 1.66 in 2025) | [AGBI, Jan 2026](https://www.agbi.com/oil-and-gas/2026/01/saudi-companies-face-cost-increase-as-aramco-ups-diesel-price/) |
| Fuel use | 35 L/100 km loaded tractor-trailer | **Assumption** → ≈ SAR 0.72/km incl. VAT |
| Driver base pay | ≈ SAR 4,000–5,500/month | [Payscale](https://www.payscale.com/research/SA/Job=Heavy_%2F_Tractor-Trailer_Truck_Driver/Salary) (indicative, thin data) |
| Market rate check | Dammam→Riyadh container ≈ USD 1,000–1,400 (≈ SAR 3,750–5,250); "full to Riyadh, back empty" | Forwarder blog, unsourced; sanity check only |

## Operating rules (unverified)

A 2017 report on the regulator's truck rules: 9 h driving/day, 56 h/week, 90 h/fortnight, 45 min break after 4.5 h, 11 h daily rest, 48 h weekly rest ([Gulf Business](https://gulfbusiness.com/?p=114994)). The TGA's current bus rules are similar (9 h/day, extendable to 10 h twice a week). **Treat as a configurable default policy, not legal compliance**, until checked against the TGA truck driver guide at tga.gov.sa.

## Demand context

- Domestic road freight: 209 Mt in 2022, +6.1% ([GASTAT](https://www.stats.gov.sa/en/news/502)). No public regional origin–destination matrix was found.
- Ports 2025: 8.32 M TEU nationally, +10.6% ([Container News](https://container-news.com/mawani-reports-10-58-growth-in-container-throughput-in-2025)). Jeddah handled 47.3% of TEUs; Dammam led bulk inbound with 39.2 Mt ([Hellenic Shipping News](https://www.hellenicshippingnews.com/?p=1148838)).
- Market: TGA cites 500,000+ trucks and 18,500 licensed transport companies ([GDN](https://www.gdnonline.com/Details/1378568/Saudi-Arabia-readies-500,000-truck-fleet-for-smooth-GCC-freight-movement-)). Rail moved a record 30 Mt in 2025, shifting some east–west volume off roads.
- Empty running: no Saudi figure found. A World Bank meta-analysis of 27 countries averages 29% empty miles ([World Bank](https://documents.worldbank.org/en/publication/documents-reports/documentdetail/099308205162416769)).
- Regulation: foreign trucks need a Bayan electronic transport document; domestic operations are documented on TGA's Logisti platform. Both are integration candidates.

## Solver benchmarks (not downloaded)

- Srour et al., 165 real full-truckload drayage instances (Rotterdam, 40 trucks, 65 jobs/day): [ERS-2010-036-LIS](https://repub.eur.nl/pub/20883).
- Sartori & Buriol, 300 PDPTW instances (100–5,000 locations) with validator and best-known solutions: [Mendeley Data](https://data.mendeley.com/datasets/wr2ct4r22f/2).
