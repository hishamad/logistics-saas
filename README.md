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
    planning/            planners: greedy baseline + CP-SAT optimizer (to be replaced)
    ai.py                turns Arabic/English dispatcher instructions into typed rules (parked)
    cli.py               command line: plan a scenario
  scripts/               scenario generator
  tests/                 engine tests
data/saudi/              real road network (28 sites) + generated scenarios
data/benchmarks/         public academic test problems
docs/                    product brief, Saudi road freight guide, reference screenshots
scripts/                 builds the road network from OpenStreetMap
```

## Run it

You need [uv](https://docs.astral.sh/uv/). From `backend/`:

```bash
uv sync
```

```bash
uv run freight plan ../data/saudi/scenarios/pilot/snapshot.json
```

```bash
uv run pytest
```

Current result on the pilot scenario (40 trucks, 48 h): 55 of 56 jobs served, **47% of kilometres driven empty**, SAR 81,529 modeled cost. This is the number to beat.
