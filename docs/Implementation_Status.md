# MVP implementation status

**As of 10 October 2026:** The MVP has completed a substantial hardening pass. Python/FastAPI, PostgreSQL, CP-SAT and the English/Arabic interface are connected. The real OpenAI gateway passes **16/16 synthetic language cases** with `gpt-6-luna` and `low` reasoning, and a real Arabic browser instruction has been approved and verified in a resulting plan. A separate OIDC production configuration and deployment files are implemented. **This is not a declaration of customer production readiness:** the actual host, identity provider, backups/monitoring and customer operating assumptions still need commissioning. See the [deployment runbook](Deployment.md).

Start with [the README](../README.md). The reviewed [PRD](../Saudi_Freight_Dispatch_PRD.md) and [implementation plan](Implementation_Plan.md) remain the broader staged specification.

## Implemented and exercised

| Area | Working behavior |
| --- | --- |
| Domain and costs | Timezone-aware, fixed-team FTL inputs; decimal SAR costs; separate optimization penalties; missing-cost comparisons disabled |
| Independent validation | Windows, equipment/capacity, location continuity, full FTL job occupancy, resource overlap, loaded/empty movement, waiting, calendars, locks and terminal obligations |
| Planning | Deterministic insertion baseline and CP-SAT sequencing; strict service requirements; explicit diagnostic partial coverage; distinct infeasible/unknown/invalid outcomes; validated warm starts |
| Persistence | Real PostgreSQL, Alembic migrations, tenant-qualified records, immutable input revisions, hashes and audit events |
| Imports | Jobs/resources/lanes CSVs; reusable mappings; stable IDs; raw source/checksum retention; row review and overrides; idempotent commit; optimistic revisions; source-vs-dispatcher conflicts |
| Worker | Separate Python process; atomic `SKIP LOCKED` claim; renewable leases; bounded attempts; cancellation and reclaimed-attempt write fencing |
| UI | English/Arabic and RTL; planning board, resource timeline, history, job corrections, assignment/time locks, rule review, cost assumptions, import review and review-only plan export |
| OpenAI path | Official Responses structured parsing; tenant entity checks; explicit revision-bound approval; provider failure/refusal/incomplete handling; manual fallback; no model access to operational mutation tools |
| Identity and boundaries | OIDC code flow with PKCE, issuer/audience/signature/nonce validation, explicit memberships, dispatcher/viewer roles, secure opaque sessions, same-origin requests and bounded bodies |
| Operations | Separate runtime database credentials, TLS/container configuration, queue-stall health reporting, safe request metadata logs and a completed isolated backup/restore drill |
| Developer workflow | Locked dependencies, generated OpenAPI types, strict Python/TypeScript checks, local start/stop/check scripts, CI configuration |

The first-build scope uses versioned input edits and assignment locks followed by replanning. Free-form manual editing of arbitrary plan activities, imported dispatcher-assignment baselines, and an actual customer update connector remain deferred. Do not read this table as a claim that every M1/M2A or PRD acceptance item is complete.

## Verification evidence

- **56 backend tests** cover independent arithmetic and scheduling, shared resources, horizon spillover, required terminal moves, merged calendar blocks, exact locks, missing waiting, interleaved FTL jobs, and explicit financial-comparison eligibility. Additional cases cover large objective values, missing costs, partial CSV mappings, safe spreadsheet exports, AI concurrency/quotas, worker claim races, stale revisions and production authorization.
- The tiny independent oracle enumerates all assignments and route orders, including time-window feasibility, and checks CP-SAT's distance optimum against that exhaustive result. Both broad and tighter windows are covered.
- A second independent brute-force scheduling oracle verifies 40 generated small cases with different time windows, service durations and travel times against CP-SAT, including duty-cost optima.
- Real PostgreSQL tests apply migrations into a unique schema per test. They cover cross-tenant access, reviewed reimports, source conflicts, atomic fixed-team relocation, optimistic concurrent writes, idempotency, commit-before-response failure, stale leases, cancellation, plan export and explicit rule approval.
- Offline AI tests cover unsupported/ambiguous or unknown-entity proposals and incomplete, refused, rejected and unavailable provider responses. The separate [live smoke report](ai-smoke-evaluation.json) records real provider results: all four rule types in both languages, explicit soft preferences, missing tradeoffs, ambiguity, unsupported actions and multiple-rule requests. All ten supported cases produce independently valid, complete plans. This small suite is not a customer accuracy estimate.
- Chromium workflows cover planning/manual approval/import/persistence/Arabic/RTL/mobile; transient polling failure; duplicate clicks; stale open forms; safe AI failure; ambiguous AI retry identity; production sign-in presentation; and a separately opted-in live Arabic AI approval/replanning path. Screenshots are under `.runtime/screenshots/`. The six regular test cases include combined workflows; the seventh makes one paid provider call.
- OIDC tests run an actual signed-token authorization-code flow against a test transport, checking PKCE, nonce, issuer, audience, expiration, bad signature, state and membership. Viewer writes and revoked memberships are rejected by the API. A real external identity provider remains unverified.
- Ruff, strict mypy, TypeScript, Prettier and the optimized Next.js production build pass. The Windows startup script has launched all three services successfully. The GitHub Actions file is supplied but has not been executed on hosted CI.
- Python and npm dependency audits reported no known vulnerabilities. This is a point-in-time dependency check, not a penetration test. Docker is not installed locally; the Compose structure has been inspected, but the images and gateway need a real container run.
- A PostgreSQL custom-format backup was restored into a fresh uniquely named database and its migration version, workspaces, revisions and runs were read successfully. The temporary restore database was then removed; the source was preserved. See [restore evidence](backup-verification.json). Off-host encrypted backups and recovery objectives remain deployment work.

The desktop browser-control tool could not initialize because of the host's Windows sandbox setup error. Project-local Playwright/Chromium provided the browser verification instead. This did not replace backend or transaction tests with mocks.

## Measured scale check

See [raw benchmark output](benchmark.json). This is a single local synthetic measurement, not a performance SLA or a customer saving claim.

| Setting/result | Measurement |
| --- | --- |
| Machine | Windows 11, AMD Ryzen 7 3700X, 8 cores / 16 logical CPUs, approximately 16 GB RAM |
| Runtime | Python 3.13.1; OR-Tools 9.15.6755; one solver thread; seed 7 |
| Scenario | 50 teams, 150 confirmed jobs, 48-hour decision horizon; synthetic lane matrix |
| Eligible job/team combinations | 4,560 of 7,500 (60.8%) |
| Model | 265,189 variables, 292,999 constraints, 246,596 sequence/depot arcs |
| Greedy baseline | All 150 served, independently valid; 16.538 s |
| CP-SAT with validated baseline hint | All 150 served, independently valid; feasible, optimality not proven; 30.468 s wall time for a configured 30 s budget |
| Model construction included above | 8.779 s |
| Independent result validation | 6.148 ms baseline; 6.645 ms CP-SAT in the recorded run |
| Sequential planning/validation total | Approximately 47.0 s, excluding API queue delay |
| Modeled cost | SAR 42,770.42 for both plans; **no modeled improvement demonstrated** |

An earlier cold CP-SAT attempt returned **unknown** within the budget. Passing a complete independently validated hint and avoiding the large-model presolve yielded a feasible incumbent. The original outcome was not relabeled or silently substituted. The larger model still needs performance and solution-quality work before a pilot. Timed native solver cleanup can slightly exceed the configured budget. Cancellation immediately fences result acceptance; an active computation may finish its current bounded attempt before the worker takes another task.

## Remaining gates

1. **Deployment commissioning:** Build/run the containers, connect the actual HTTPS domain and OIDC provider, provision exact subject memberships, test role changes/session revocation, and run a restore and availability drill on the target host. The [runbook](Deployment.md) makes these steps concrete. No customer deployment or hosted CI run has occurred in this task.
2. **Customer evidence:** Obtain a qualified dispatcher, a real approved data/update sample, reliable costs/lanes, known-at history and concrete operating rules. Test refresh and setup effort, willingness to pay, recommendation usefulness and supported pairing assumptions.
3. **Shadow readiness:** Validate supported operational policy, implement the agreed customer update adapter, import historical baselines, evaluate fuller localized diagnostics and establish ongoing data freshness and language accuracy. Identity/membership and local backup/restore are implemented; their deployment configuration remains a gate. Owned-capacity offered-job economics is a later product stage.
4. **Live readiness:** Publication authority, external commitments/reservations, outbox delivery/reconciliation and acknowledgments are separate work. There is no publication endpoint, driver app, marketplace or automatic booking in this build.

The implementation demonstrates a persisted, language-driven planning and human-review loop. It does not establish market fit, real-world route accuracy, legal driver-hour compliance, realized savings or production deployment readiness.
