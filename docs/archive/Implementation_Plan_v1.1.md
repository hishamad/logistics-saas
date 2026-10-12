# Saudi Freight Dispatch Critical Review and Implementation Plan

**Date:** 10 October 2026  
**Companion specification:** [PRD version 1.1](../Saudi_Freight_Dispatch_PRD.md)  
**Repository at review:** One untracked PRD; no application, dependency manifest, migrations or tests. The prospect workbook mentioned in the PRD is not present in this checkout.

Build a reliable planning loop for one dispatch team, then test it in shadow mode with real operating data. Use a Python backend and the OpenAI API for reviewed language tasks. The first implementation should establish whether the system can produce feasible assignments and defensible comparisons; the dispatcher UI, document AI and live execution then build on that foundation.

This document records the critical review, chosen starting architecture and implementation work packages. It does not represent implemented or benchmarked software.

## 1 Critical assessment

The PRD is strongest on the distinction between optimization and operations: independent validation, explicit commitments, revisioned publication, grounded costs and honest evidence. Keep those requirements. The main weakness is sequencing: version 1.0 makes intake AI, optimization, commercial simulations, a driver product, integrations and historical evaluation prerequisites for the first sellable release. That postpones learning whether dispatchers have a valuable planning problem and whether usable data exists.

The most important business uncertainty is access to trustworthy starting states, windows, assignments and costs. A sophisticated optimizer cannot repair unknown cargo custody, stale trailer locations or a workflow in which the dispatcher does not control capacity. Qualify customers by their actual operating pattern and decision authority, not truck count alone.

| Finding in version 1.0 | Consequence | Correction in version 1.1 |
| --- | --- | --- |
| Almost every capability is P0; shadow/evidence work follows execution | Large build before useful customer feedback | Separate R0 runnable loop, R1 shadow, R2 supervised live and R3 extensions; move shadow evidence ahead of execution |
| Provider-neutral AI despite the founder selecting OpenAI | Unnecessary abstraction and an unresolved decision | Official OpenAI Python SDK and Responses API; one narrow gateway |
| Fixed and alternative resource teams both expected immediately | Adds location-dependent coupling and crew scheduling before the core is proven | Separate resource entities, fixed approved teams first; qualify the pilot for that restriction |
| Snapshot IDs/hash without a concrete consistent-read or revision strategy | A reproducible-looking snapshot could mix incompatible versions or use hindsight | Consistent immutable input, per-revision known-at timestamps and versioned travel/cost assumptions |
| Stale and validated mixed into plan lifecycle; acknowledgment mixed into job execution | A published plan loses its history or a draft can corrupt operational status | Separate lifecycle, validity, coverage, assignment and version-specific acknowledgment |
| Scope locking is described without a cross-scope resource guard | Two valid-looking publications could reserve the same trailer | Transactional resource reservations and overlap protection across scopes |
| Worker retries assumed never to duplicate an external instruction | A crash after an ambiguous send cannot be made exactly-once locally | Stable instruction IDs, provider/recipient dedupe and delivery_unknown reconciliation |
| In-progress work protected without defining a stranded loaded trip | Breakdown recovery could force impossible continuation or teleport cargo | Preserve observed custody/location and expose unsupported rescue as an exception |
| Objective ordering lacks timeout/partial-proof semantics | A partial or time-limited result could be called globally optimal | Strict versus diagnostic formulations and per-objective-stage status |
| Revenue and cost completeness coupled too broadly | Missing sales price unnecessarily blocks cost optimization; missing costs can bias it | Separate feasibility, cost comparison and contribution readiness |
| Offered-job test need not force service; baseline search quality is unspecified | A dropped offer or unrelated baseline improvement can inflate contribution | Force the offered job in the test, preserve obligations and expose comparison uncertainty |
| Independent validator has no code-level independence requirement | A shared modeling mistake can validate itself | Separate checking algorithm over final activities, tiny independent oracle and hand-calculated costs |

No source in the PRD establishes buyer demand, customer savings or the usefulness of the stated fleet-size segment. The revision retains those as hypotheses. It also preserves the ambition to expand; deferred capabilities are explicit rather than quietly omitted.

## 2 The first product to prove

The initial workflow is:

1. Import a template of confirmed jobs, resource teams and existing commitments.
2. Review locations, windows, units, availability and costs; leave unresolved data visible.
3. Take an immutable snapshot with approved lane times and an explicit end-state policy.
4. Evaluate the imported dispatcher plan and a deterministic baseline.
5. Produce and independently validate a CP-SAT candidate.
6. Compare equivalent service, cost components, empty distance, assignments and exceptions.
7. Lock or edit a future assignment, solve again and inspect the differences.
8. Export a labelled shadow result and record the dispatcher's acceptance or rejection reason.

Start with one depot, dedicated pickup-to-delivery jobs, fixed teams, a 48-hour decision horizon, SAR and Asia/Riyadh operational time. Preserve activities extending beyond the horizon. Tiny fixtures use fictitious sites and explicit synthetic lane values; customer trials use approved real inputs.

The first customer-visible release needs spreadsheet intake, review, a usable jobs/resource timeline, manual structured constraints and credible comparisons. AI can reduce input/review effort once that loop works. A paid shadow evaluation is a valid scoped product if its limitations are explicit and the customer agrees to its objective.

Defer generic chat, maps beyond useful location context, drag/drop polish, partner procurement, offer pricing, automatic team changes, full historical replay and live driver delivery. If a qualified pilot requires one of these to obtain value, change its scope explicitly and add the required acceptance checks; do not build all of them speculatively.

## 3 Architecture decisions

| Concern | Starting decision | Why |
| --- | --- | --- |
| Backend | Python modular monolith with FastAPI and Pydantic | One domain implementation shared by API, workers and tests |
| Persistence | PostgreSQL, SQLAlchemy and Alembic | Durable revisions, snapshots, tenant constraints and transactions |
| Optimization | OR-Tools CP-SAT behind a small planner interface | Initial assignment/sequencing formulation can use integer variables and explicit status handling |
| Validation and cost | Pure Python modules with no HTTP/ORM/CP-SAT dependency | Direct fixture testing and independent checking of solver/manual plans |
| Background work | PostgreSQL durable jobs; separate Python worker entry points | Reuse one operational datastore at pilot scale; make recovery and fencing explicit |
| Frontend | React/TypeScript with Next.js; generated OpenAPI client | Typed client and bilingual dispatcher interaction; business logic remains in Python |
| AI | OpenAI Responses API and typed proposals | Constrained, reviewable extraction and rule interpretation |
| Travel | Operator-approved lane table first; versioned provider interface | Customer-specific heavy-truck feasibility needs defensible travel assumptions |
| Identity | Established OIDC authentication; Python enforces membership and scope | Avoid implementing a password system; auth supplier can be selected before R1 deployment |
| Local development | uv, locked Python dependencies, pytest, Ruff, type checking and Docker Compose | Reproducible setup and straightforward validation |

Pin compatible stable versions when M0/M1 are implemented and verify the OR-Tools wheel on the chosen Python interpreter and deployment platform. Do not copy an unverified latest version into the spec.

CP-SAT requires integer constraints and distinguishes feasible, optimal, unknown and infeasible results; map those outcomes without inventing a proof. [OR-Tools documentation](https://developers.google.com/optimization/cp/cp_solver).

The PostgreSQL queue is a design choice, not a claim that row locking supplies durable retries automatically. Keep claims short, perform work outside transactions, heartbeat leases, fence stale attempts and commit results idempotently. PostgreSQL documents SKIP LOCKED for queue-like use. CPU-heavy work belongs outside the request process. [PostgreSQL locking](https://www.postgresql.org/docs/current/sql-select.html), [FastAPI background work](https://fastapi.tiangolo.com/tutorial/background-tasks/).

Apply tenant-qualified foreign keys and scoped queries from M1. Add/test row-level security with a non-owner runtime role before customer data; RLS has privileged-role and table-owner exceptions. Do not treat it as a substitute for API authorization. [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).

Use ordinary polling initially. No Redis, Kafka, Kubernetes, agent framework or vector database is needed to test this product. Introduce infrastructure only for a demonstrated need. API and worker process separation does not require separate domain services or separate databases.

## 4 Concrete implementation work packages

### M0 Executable planning domain

Build one installable Python package and a CLI using synthetic JSON fixtures. Do not start with a broad set of screens or empty service scaffolds.

**Deliverables**

- Canonical types for jobs, stops, tractors, trailers, drivers, fixed teams, availability, current/future commitments, policies, lane estimates, costs, snapshots, activities and validation findings.
- Separate fields for commercial state, data readiness and execution. Distinguish unknown from zero; use UTC instants with operational timezone context, canonical units and precise monetary rates.
- A deterministic planner that orders jobs by documented priority/deadline and inserts them into eligible teams at the lowest validated incremental cost. Explicitly report unserved work; the heuristic need not find every feasible plan.
- A final-plan validator that reconstructs paths, times, occupancy, windows, capacity, eligibility, resource availability and terminal obligations. It checks current loaded state and horizon spillover.
- A cost calculator with itemized distance/time/handling costs, exclusions and missing-input status. Search penalties never appear as cash expenditure.
- Feasible and conflicting cases with 2–4 teams and 3–6 jobs, plus explicit expected findings and hand-calculated totals. Use separate exhaustive enumeration over a bounded tiny integer-time domain for the later solver oracle.
- A CLI command, proposed as `uv run freight plan --fixture fixtures/tiny_feasible.json`, producing the snapshot ID/hash, baseline activities, findings, coverage and cost report. This command is a target interface, not available yet.

**Exit check:** A developer can inspect one complete plan and its arithmetic by hand. Tests reject shared-trailer overlap, impossible empty repositioning, unavailable drivers, tight-window violations and a falsely freed resource after the horizon. Missing material costs disable monetary comparisons. There is no OpenAI or network dependency.

### M1 Persisted operational foundation

Add FastAPI, PostgreSQL migrations and one transaction layer. Persist only the entities needed for the first planning loop; do not create speculative billing, marketplace or proof-of-delivery modules.

**Deliverables**

- Tenant/scope membership boundary and two synthetic tenants for isolation tests. Any local authentication fixture is loopback/demo-only and cannot be deployed for real customer access.
- Jobs/resources/sites/teams, immutable revisions, raw import values, source checksums, review decisions and audit events.
- CSV templates for jobs, resources, lane estimates and baseline assignments. Row identity supports repeated legitimate jobs; file reupload and row revision deduplication are distinct operations.
- A review/commit API with idempotency keys, request hashes and optimistic version checks. CSV parser errors and conflicting reimports produce review items.
- Durable task records, leases, fencing and restart recovery. Introduce a single task implementation before adding multiple worker types.
- Database-backed unit/integration boundaries and an initial generated OpenAPI client. Reserve API paths only for implemented capabilities.

**Exit check:** Import → review → commit survives restart. Repeat import cannot duplicate logical records; a conflicting revision cannot overwrite a dispatcher correction. Tenant B cannot retrieve Tenant A's import, source or run. A reclaimed worker lease cannot let the old attempt overwrite results.

### M2 End to end planning loop

Add CP-SAT and the smallest useful board after the domain and persistence boundaries work.

**Deliverables**

- A consistent snapshot transaction and immutable plan inputs, including baseline, policy versions, matrix values, known-at times and terminal obligations.
- Fixed-team candidate generation and sequencing: job/team assignment, service timing, sequence-dependent repositioning, availability and independent occupancy for tractor/trailer/driver. Prune only on defensible necessary conditions; compare pruning against tiny unpruned fixtures.
- Strict-complete runs with all confirmed jobs required. Offer diagnostic-partial runs explicitly after a strict failure/timeout, preserving the original outcome and total time budget. Unknown is not proven infeasible.
- Priority/service ordering, cost/churn breakdown and bounded solving. Hints and heuristic incumbents are validated against the same snapshot; they are not a feasibility guarantee.
- API endpoints for solver runs/progress/cancellation, plan detail/comparison and versioned draft edits/locks. Manual edits create a draft revision and run the same final-plan validator.
- One page with jobs, resource timeline, review issues and comparison details; persisted state and job polling. Form controls before drag/drop. Establish RTL/localized message infrastructure now.
- Tiny oracle comparisons and a benchmark report for 50 teams/150 jobs/48 hours, including actual hardware, solver settings, candidate density, coverage, validation time and end-to-end latency.

**Exit check:** A fresh checkout can run import → review → solve → validate → compare → lock → replan. The API remains responsive while a worker solves. A timeout, cancellation or worker restart preserves previous results and records the new outcome correctly. Performance misses are reported without weakening constraints. This completes R0, not a live dispatch release.

### M3 Customer shadow pilot

Finish production authentication/scoped access, private source access, XLSX mappings, Arabic/English flows, structured rules, freshness confirmations, baseline import, supported future-work disruption scenarios, exports and tested restore. Use current operator-approved lane data and policies. A customer can reject or annotate recommendations and identify missing rules.

**Exit check:** One qualified dispatch team can review its own current data and compare an eligible plan against its existing assignments. The export reconciles with on-screen values and includes unresolved issues. Publication remains disabled. Record review time and rejection reasons without calling modeled deltas realized savings.

### M4 OpenAI language tasks

Implement pasted-text JobExtractionProposal first, then RuleProposal for a small allowlist such as resource unavailable, equipment required and preferred assignment. Structured/manual rule semantics must already exist; AI only proposes their parameters. Add PDFs/images once intake preview and evaluation are reliable.

Use the official Python SDK's Responses parsing with Pydantic schemas. Explicitly handle refusals and incomplete responses, then run domain validation: schema correctness is not operational correctness. [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Configure `OPENAI_API_KEY`, `OPENAI_MODEL_EXTRACTION` and `OPENAI_MODEL_RULES` in backend secrets. The founder provides the key when real calls are tested; do not put it in chat, the web client, source control or logs. The model choice follows a held-out Arabic/English evaluation and account availability; model names and pricing are not assumed by this plan.

Use `store=false` by default and minimize input data. That setting does not mean Zero Data Retention; approve the actual provider processing and file-retention configuration before customer documents are sent. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

**Exit check:** Source-backed proposals remain inactive until reviewed; ambiguous dates/units/entities prompt clarification; provider/key failures leave manual planning usable. Report critical-field errors separately from aggregate accuracy, plus review effort, latency and token usage. No AI output can call a publication endpoint or directly write domain state.

### M5 Supervised live dispatch

Implement exact-version approval, cross-scope reservation checks, atomic publication/outbox and one selected authoritative driver or TMS channel. Resolve ambiguous sends; distinguish publication, delivery and acknowledgment. Test an actual staging integration and customer operating procedures before enabling live mode.

**Exit check:** Concurrent publication, expired assumptions, worker crashes, duplicate events and old-version acknowledgments behave according to the PRD. The customer approves authority, supported disruption behavior, exception ownership and the delivery/update path. Imported live commitments constrain planning before the system starts publishing its own instructions.

### M6 Extensions and M7 repeatable rollout

Prioritize partner offers, new-job contribution and full as-of replay only after observing their value. Keep per-revision knowledge timestamps from M1 so replay remains possible later. Measure onboarding effort, support load, compute/provider costs, dispatcher adoption and willingness to pay before expanding to another segment.

## 5 Initial acceptance mapping

This maps the major work packages to the PRD acceptance suite. Individual tests can begin earlier; a later stage must still pass all applicable earlier checks. For multi-part scenarios, record the covered subset explicitly. Extend the checklist before enabling a deferred capability.

| Work package | Primary acceptance coverage |
| --- | --- |
| M0 domain | AC-05–09, 11, 13–14, 24–25, 27, 40, 42, 46; synthetic fixed-team subset |
| M1 persistence | AC-01–02, 31, 37, 45; source/import/run isolation now, other resources when introduced |
| M2 planning | AC-07–09, 11, 13–14, 22–25, 29, 31, 35, 40, 42, 44, 46; provider outage uses an explicit test adapter |
| M3 shadow | AC-12, 15–16, 30, 32, 34, 38–39 plus earlier checks on customer data; publication-related parts remain disabled |
| M4 AI | AC-03–04, 12, 36 plus key absence, timeout, refusal, incomplete output and semantic-error tests |
| M5 live | AC-17–21, 33, 35, 38–39, 43, 45; no partner quote path until that extension is enabled |
| M6 extensions | AC-10, 26, 28, 41, 47 and full replay/publication/partner interactions |

Avoid tests that only mirror ORM field names or mock away the invariants being checked. Use real PostgreSQL for transaction, tenant and concurrency tests, and independent expected results for costs and solver fixtures.

## 6 Customer evidence to obtain while coding

Ask a qualified operator for an approved/anonymized sample covering several ordinary operating days, ideally 5–10, including difficult days rather than only clean examples. This is a proposed discovery package, not a prerequisite for synthetic M0 work.

- Jobs, creation/known-at timestamps, pickup/delivery window meanings, equipment/cargo requirements, service durations and cancellations.
- Resource start locations, current loaded work, team pairings, availability, maintenance and relevant operating-policy history.
- Actual assignments, changes and reasons; approved lane times/distances; costs with inclusions/exclusions.
- Which system/role owns each field, how updates arrive, how often they become stale and which future assignments can change.
- Who can accept recommendations, who can authorize spending and which measurable planning problem would justify paying.

Before R1, require a named dispatcher willing to review results, an approved data/update path, a supported fixed-team workflow and an agreed evaluation objective. If missing data cannot be resolved without continuous custom operational work, treat that as a product/business finding rather than hiding it behind defaults. If the existing TMS already solves the problem acceptably, find a demonstrable gap before building more features.

The founder still needs to resolve the pilot customer, publication channel, deployment/processing requirements and pricing through actual customer evidence. None prevents starting the small deterministic Python increment. The next implementation task is M0; the larger milestones are sequenced work, not a promise that one coding run will deliver the complete system.
