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
    api/                 web API: logins, companies, background plan runs (FastAPI)
    ai.py                turns Arabic/English dispatcher instructions into typed rules (parked)
    board.py             plan board: renders a plan as a self-contained HTML timeline
    demo.py              carrier demo: a simulated week as a bilingual result sheet + daily boards
    explain.py           why / what-if: computed facts, explained by AI or a built-in template
    cli.py               command line: plan a scenario
  scripts/               scenario generator
  tests/                 engine tests
web/                     the dispatcher web app (React + TypeScript, Vite)
data/saudi/              real road network (28 sites) + generated scenarios
data/benchmarks/         public academic test problems
docs/                    product brief, engine research, Saudi road freight guide, reference screenshots
scripts/                 builds the road network from OpenStreetMap
```

## Run the web app (development)

Two terminals. First time only: `uv run python scripts/seed_dev.py` in `backend/` creates a local demo company; its test logins are listed in that file (local use only). And `npm install` in `web/`.

API, from `backend/`:

```bash
uv run uvicorn freight.api.app:create_app --factory --port 8000
```

Web app, from `web/` (then open http://127.0.0.1:5173):

```bash
npm run dev
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

**The carrier demo.** Simulates a dispatch week (every morning plans 48 h from the orders known by then) and writes a small website to open or email: `index.html` is a one-page result sheet in English and Arabic, and `day-1.html` … `day-7.html` are the plan boards per morning with "changes since yesterday". `--rounds` makes the result exactly repeatable.

```bash
uv run freight demo ../data/saudi/scenarios/full/snapshot.json --out ../boards/demo --rounds 6000 --seed 1
```

**Why and what-if.** The engine computes the facts and an AI model (OpenAI, key in `backend/.env`) explains them in English or Arabic; without a working key a built-in template explains instead. What-if answers isolate the change: they compare against a control re-plan with the same effort and only move what the change forces.

```bash
uv run freight explain ../data/saudi/scenarios/pilot/snapshot.json --job SA-26006 --lang ar
```

```bash
uv run freight whatif ../data/saudi/scenarios/pilot/snapshot.json --unavailable team-DMM-012 --from 2026-10-18T14:00+03:00 --to 2026-10-19T02:00+03:00
```

To compare daily re-planning policies over a simulated week (freeze window, change penalty, look-ahead), run `uv run python scripts/daily.py` ([results](docs/benchmarks/daily.md)). To measure the engine (exact gaps on small scenarios, bound gaps on the pilot and the full week), run the command below. Results land in [docs/benchmarks](docs/benchmarks/README.md).

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
