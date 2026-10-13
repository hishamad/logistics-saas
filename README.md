# Saudi freight planning

A planning engine for Saudi full-truckload fleets. The engine takes the trucks, drivers and jobs a carrier has and works out who should do what, in which order. The goal is fewer empty kilometres and more revenue per truck.

We're building it step by step. The first one-shot build is preserved under the git tag `one-shot-baseline`.

## What's here

```
backend/                 Python planning engine
  src/freight/
    domain/              data model: sites, trucks, drivers, teams, jobs, plans
    validation/          independent checker: is a plan physically possible?
    costing/             modeled cost of a plan (fuel, distance, driver time)
    planning/engine.py   the planner: route simulator with driving-hours rules + ruin-and-recreate search
    planning/            older planners kept for comparison: greedy baseline, CP-SAT
    ai.py                turns Arabic/English dispatcher instructions into typed rules (parked)
    board.py             plan board: renders a plan as a self-contained HTML timeline
    cli.py               command line: plan a scenario
  scripts/               scenario generator
  tests/                 engine tests
data/saudi/              real road network (28 sites) + generated scenarios
data/benchmarks/         public academic test problems
docs/                    product brief, engine research, Saudi road freight guide, reference screenshots
scripts/                 builds the road network from OpenStreetMap
```

## Run it

You need [uv](https://docs.astral.sh/uv/). From `backend/`:

```bash
uv sync
```

```bash
uv run freight plan ../data/saudi/scenarios/full/snapshot.json --seconds 60
```

Add `--board ../boards/week.html` to also write the **plan board**: a single HTML file showing every truck's week on a timeline, with hover details, itineraries and unserved jobs. It opens in any browser without a server. Add `--method baseline` to run the old greedy planner, or `--confirmed-only` to ignore offer loads. `--lookahead` values where trucks end the plan (experimental; see the engine research for why it is not the default).

```bash
uv run pytest
```

To measure the engine (exact gaps on small scenarios, bound gaps on the pilot and the full week), run the command below. Results land in [docs/benchmarks](docs/benchmarks/README.md).

```bash
uv run python scripts/benchmark.py
```

## Results so far (13 Oct 2026, synthetic scenarios, one laptop)

**Pilot:** 40 trucks, 48 h, classic rules (every truck returns to its depot), 30 s.

| | Old greedy | New engine |
| --- | --- | --- |
| Confirmed jobs served | 55/56 | 55/56 |
| Modeled cost, confirmed only | SAR 81,682 | **SAR 78,605 (−3.8%)** |
| Empty km, confirmed only | 22,401 | 20,964 |
| Contribution with offer loads | SAR 129,661 (can't use offers) | **SAR 162,167 (+25%)** |

**Full week:** 100 trucks, 7 days, realistic rules (driving hours, weekly day off at home, trucks end where they are), 60 s.

| | Old greedy | New engine |
| --- | --- | --- |
| Confirmed jobs served | 19/490 | **463/490** |
| Offer loads accepted | — | 49/122 |
| Empty km | — | 31% |
| Revenue per truck-day | — | SAR 2,631 |

The roughly 25 unserved jobs in the full week look like a capacity limit of the scenario, not of the search: a 3-minute run serves 468, almost the same as after 60 s. Every plan passes the independent validator. All numbers come from synthetic demand on real roads; none of them are customer results.
