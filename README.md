# Madar · Saudi freight planning MVP

A freight-planning MVP inspired by Fleetline's operational-rule → reviewed interpretation → optimization loop. “Madar” is a UI working name, not an approved brand. Local startup uses synthetic data; a separate production configuration supports reviewed shadow workspaces and organizational sign-in.

The Python backend and real PostgreSQL/CP-SAT planning flow work without AI credentials. **Live OpenAI verification now passes 16/16 Arabic/English smoke cases with `gpt-6-luna`, plus a real Arabic browser approval/replanning workflow.** Nothing in this application publishes dispatch instructions. Read the [deployment runbook and remaining release gates](docs/Deployment.md) before hosting it.

## Start on this Windows machine

From the repository root:

```powershell
.\scripts\start-demo.ps1
```

Then open [the local application](http://127.0.0.1:3000). Choose either synthetic workspace. Subsequent starts can use `-SkipInstall` once dependencies are installed. Add `-ProductionWeb` to build and serve the optimized frontend; the backend still uses local demo authentication.

The script requires `uv`, Node.js/npm and PostgreSQL's `initdb`, `pg_ctl`, `psql` and `createdb` on PATH. It creates an isolated database cluster under `.runtime/postgres` on **127.0.0.1:55432**, applies Alembic migrations, and starts the API, worker and frontend in hidden background processes. It does not change an existing PostgreSQL service. This machine's available PostgreSQL 13.4 installation was used for local verification; use a maintained PostgreSQL release for any later deployment. Local cluster authentication is trust-based and is strictly for this synthetic loopback demo.

Use an existing configured PostgreSQL instance instead with `-ExternalDatabase`; first set `DATABASE_URL` in `backend/.env`.

Stop the app and worker:

```powershell
.\scripts\stop-demo.ps1
# Also stop the isolated local database:
.\scripts\stop-demo.ps1 -StopDatabase
```

Logs and process records live in `.runtime/`. Runtime data, dependency directories and `.env` are ignored by Git. Stopping the services preserves data. `start-demo.ps1` refuses occupied app ports instead of terminating other applications.

## Try the first planning loop

1. Choose **Eastern Freight** and review its synthetic jobs and resource assumptions.
2. Select **Optimize plan**. A separate durable worker computes a greedy baseline and a CP-SAT candidate from the same saved revision.
3. Inspect assignments, resource occupancy, coverage and cost. “Feasible” does not mean optimal; “unknown” does not mean infeasible. No complete result triggers an explicit coverage-diagnostic option.
4. Add a structured rule requiring `SFD-1041` to use `Team 02`, then optimize again. The old result stays available with a stale-input notice until the new result arrives.
5. Lock an assignment, optionally at an exact pickup time, or correct a job's windows/weight. Replan to validate those changes against all commitments.
6. In **Data imports**, download a current CSV template, change a stable-ID row, map columns, preview, review conflicts and commit. A refresh cannot silently replace dispatcher corrections. Rows absent from a file are not deleted.
7. Inspect saved revisions through **Plan history**, download a review-only plan CSV from comparison details, and switch between English and Arabic.

Dates in the repeatable fixture are **12–14 October 2026, Asia/Riyadh**. These are scenario dates, not live operational observations. All sites, companies, drivers, distances and travel durations are synthetic. Local workspace selection is demo-only; production requires OIDC identity and an explicitly provisioned membership.

## Enable OpenAI rule interpretation

Set these values privately in the repository-root `.env` (copy `.env.example` if needed):

```dotenv
OPENAI_API_KEY=your-private-key
OPENAI_MODEL_RULES=gpt-6-luna
OPENAI_REASONING_EFFORT=low
```

Restart the API using the stop/start scripts. Local startup loads `backend/.env`, then root `.env`, and overrides stale inherited shell settings. Root values take precedence, so keep a key in one place. Direct Python commands normally prefer process environment values; the local launcher below applies the same explicit file precedence as startup. Production containers use their own environment. The key stays on the backend; no `NEXT_PUBLIC_` key is used.

The gateway uses the official Python SDK's Responses API and Pydantic structured parsing, with `store=False`, bounded output, a timeout and no automatic provider retry. Requests have durable idempotency and a workspace quota, including failed attempts. No database lock is held during a provider call. A proposal must pass schema and domain checks, reference this tenant's entities and be explicitly approved against the current revision. Ambiguity, unsupported requests, refusals, incomplete responses and provider failures cannot activate a rule. The solver and independent validator determine feasibility and money, not the language model. [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

`store=False` is not Zero Data Retention. Customer-data processing decisions belong to the later pilot gate. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

Run the optional real API smoke evaluation after configuring the key/model:

```powershell
cd backend
uv run python scripts/run_local.py scripts/evaluate_ai.py
```

It makes 16 real paid API calls using synthetic Arabic/English instructions, checks critical fields and replans supported cases. It stops early on credential/access/quota failures. It does not activate rules in the database. Results are in `docs/ai-smoke-evaluation.json`; a small smoke suite does not replace a held-out customer-language evaluation. To repeat the real Arabic browser test, start services, set `FREIGHT_LIVE_AI=1` in the test process, and run `npm run test:e2e -- live-ai.spec.ts` from `apps/web`. It creates and then removes its synthetic rule while preserving revision history.

## Architecture

```text
Next.js / React · English and Arabic
          │ same-origin API + opaque session (OIDC in production)
FastAPI ──┼── PostgreSQL workspace revisions, imports, rules, audit
          │                 │
          │          durable run queue / leases / fencing
          │                 │
          │          separate Python worker
          │          greedy baseline → CP-SAT → independent validator
          │
          └── OpenAI → typed proposal → human approval → new input revision
```

| Location | Responsibility |
| --- | --- |
| `backend/src/freight/domain` | Frozen typed planning inputs and result contracts |
| `backend/src/freight/planning` | Fixed-team routing, baseline, CP-SAT and comparable-cost rules |
| `backend/src/freight/validation` | Independent activity, cargo, resource, timing and rule checks |
| `backend/src/freight/costing` | Decimal-based SAR arithmetic and explicit missing-cost semantics |
| `backend/src/freight/imports.py` | CSV mapping, provenance, conflicts and atomic reviewed commits |
| `backend/src/freight/api` | Tenant-scoped endpoints and generated response contracts |
| `backend/src/freight/workers` | PostgreSQL claims, lease renewal, cancellation and stale-attempt fencing |
| `backend/src/freight/ai.py` | OpenAI interpretation only; no direct operational mutation |
| `backend/src/freight/auth.py`, `admin.py` | OIDC authentication, role membership and operator provisioning |
| `backend/migrations` | Alembic schema history |
| `apps/web` | Planning UI and types generated from OpenAPI |
| `deploy` | Separate runtime/migration database roles, containers and TLS gateway |

JSONB stores immutable typed snapshots/revisions, alongside relational tenant-qualified operational records and foreign keys. It avoids prematurely splitting the whole transport domain into speculative services. Inputs use optimistic revision checks; import and run retries use request-bound idempotency keys. Transactions finish before an HTTP success is sent. [FastAPI dependency scopes](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope).

Fixed approved tractor/trailer/driver teams are the supported unit of work. A shared resource cannot create extra capacity or switch teams within a scenario. Every job holds the team through loading, loaded travel, unloading and turnaround. Empty repositioning, waiting, return-to-start or explicit terminal obligations, calendar blocks and trips that extend past the decision horizon remain represented. Resource work outside its approved calendar is rejected. Whole-minute solver decisions are checked against original timezone-aware job windows.

Costs combine distance and occupied duty time. Distance rates include fuel. Fixed overhead, taxes and unmodeled tolls are excluded. Missing material rates suppress monetary comparison; soft-rule penalties are optimization tradeoffs, not cash. The solver minimizes a fixed-point unrounded objective; displayed components are recomputed with Decimal and rounded once each. Comparisons require identical input hashes, valid plans and matching served obligations. The baseline is a greedy heuristic, not a claimed historical dispatcher plan.

## Verification

With local PostgreSQL running:

```powershell
.\scripts\check.ps1
```

This runs formatting, Ruff, strict mypy, pytest against real isolated PostgreSQL schemas, OpenAPI regeneration, TypeScript and the production frontend build. Set `FREIGHT_TEST_DATABASE_URL` explicitly for another PostgreSQL instance. Tests create and remove only uniquely named test schemas. Without that variable, a direct `uv run pytest` skips the database tests, so use the check script for the complete suite. Dependency audits run in CI; locally use `uv run pip-audit` in `backend` and `npm audit` in `apps/web`.

For the real browser flow, start all services first:

```powershell
cd apps/web
npx playwright install chromium
npm run test:e2e
```

Browser tests change the synthetic workspaces: they plan, add a rule and import `review-job`. They also exercise failed requests and concurrent changes. The paid AI case is skipped unless explicitly enabled. Screenshots go to `.runtime/screenshots/`. CI configuration is provided in `.github/workflows/ci.yml`; the hosted workflow has not been run from this local task.

The standalone planner also works without PostgreSQL:

```powershell
cd backend
uv run freight plan --method baseline
uv run freight plan --method cp_sat --seconds 10
uv run freight fixture
uv run python scripts/benchmark.py
```

See [implementation status and test evidence](docs/Implementation_Status.md), the [measured benchmark](docs/benchmark.json), the [Fleetline-informed plan](docs/Implementation_Plan.md), and the [PRD](Saudi_Freight_Dispatch_PRD.md).

## Deliberate first-build boundaries

This is a hardened MVP awaiting verification in its actual hosted environment and customer shadow validation. Production authentication is implemented and tested against signed OIDC fixtures, but a real organization/provider has not been configured here. Docker is unavailable on this machine, so container builds and the TLS deployment remain unverified locally. Real TMS/ELD synchronization, imported historical assignment baselines, automatic team formation, free-form manual plan editing, offered-job economics, legal driving/rest policy certification, document extraction, live publication and driver acknowledgments remain outside this release. Some validation diagnostics and source labels remain English.

Do not infer optimization value from the demonstration: the larger synthetic benchmark currently returns the same modeled cost as its feasible heuristic start. A customer pilot still needs trustworthy costs, current lane data, operational rules, a real refresh path, and evidence of useful decisions.
