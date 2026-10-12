# Saudi Freight Dispatch Fleetline Review and Implementation Plan

**Date:** 10 October 2026  
**Companion specification:** [PRD version 1.2](../Saudi_Freight_Dispatch_PRD.md)  
**Repository at review:** One untracked PRD; no application, dependency manifest, migrations or tests. The prospect workbook mentioned in the PRD is not present in this checkout.

Build a Fleetline-inspired optimization layer that works with an operator's existing data and incorporates dispatcher knowledge through Arabic/English instructions. Use a Python backend and OpenAI for typed rule proposals. The first product demonstration must connect operational context, optimization, reviewed language-based changes and explained replanning. A deterministic engine is the first engineering dependency; it is not the entire product proposition.

This document records verified Fleetline evidence, its implications for our product, and implementation work packages. Current implemented scope and measured evidence are tracked separately in [Implementation Status](Implementation_Status.md); this plan's acceptance gates are not automatically marked complete by the presence of code. The [previous review](archive/Implementation_Plan_v1.1.md) is preserved for comparison.

## 1 What the Fleetline evidence establishes

Fleetline's public record provides more evidence than a startup idea or an attractive demo:

- YC lists it in Summer 2025 and describes optimization combined with language-driven operational changes. [YC profile](https://www.ycombinator.com/companies/fleetline).
- Optym's 27 August 2026 announcement identifies the acquired assets as Fleetline's platform and customer subscription agreements. It does not disclose a purchase price. [Acquisition announcement](https://www.optym.com/in-the-news/optym-acquires-fleetline-expanding-its-truckload-planning-technology).
- Its recruiting page reports approximately $500k in contracted ARR within three months of launch. That is a company claim about contracts, not audited collected revenue. [Algorithm-developer role](https://www.ycombinator.com/companies/fleetline/jobs/az5DIjt-founding-algorithm-developer).
- Its product site markets contract/spot planning, TMS/ELD connections, customization and an onboarding sequence extending to day 65 with onsite training. These describe its sales proposition, not independently verified outcomes. [Product site linked from fleetline.ai](https://most-version-097184.framer.app/).

This supports pursuing the category seriously. My assessment is that commercial validation and integration capability deserve more weight than the earlier review gave them. Public evidence does not establish the acquisition's financial return, the internal solver architecture, or demand for the same workflow in Saudi Arabia. The YC profile's remaining Active label is less specific about the transaction than the dated buyer announcement.

## 2 Revised critical assessment

Version 1.1 improved safety and release sequencing but moved the distinctive language-to-replanning workflow too far back. The revised scope keeps the product's central promise in the first demonstration while staging the surrounding transport-management features.

| Product question | Revised decision | Reason |
| --- | --- | --- |
| What is the initial product? | An adaptive fleet optimizer alongside current systems | Evaluate better operational decisions without requiring a whole-system migration |
| When does language-based planning arrive? | M2B, completing the first R0 demonstration | It tests whether dispatchers can supply knowledge that meaningfully changes a feasible plan |
| What does OpenAI do first? | Interpret a supported rule and ask for clarification | Generic chat and document extraction alone do not test adaptive optimization |
| How important is integration? | Prototype a real update path alongside engine work; reusable mappings in M1 | Clean one-time files conceal the ongoing data problem; refresh effort affects adoption and margin |
| Does the product only reduce costs? | Protect confirmed service, then evaluate known extra work in R1 | A bounded offered-job scenario tests utilization and incremental contribution without procurement |
| How broad is the initial optimizer? | One pilot scope and fixed approved teams, with separate resource checks | Make the hard decision loop real on a supported operating pattern; expand constraints from observed demand |
| Is a native driver product required? | Prefer the existing TMS/instruction channel; build one only when necessary | Execution integration can deliver value before replacing driver workflows |
| Can onboarding be entirely self-service? | Remote-first with hands-on mapping and dispatcher feedback | Operational knowledge must be obtained; support effort needs to be measured and priced |
| What is the potential advantage in Saudi Arabia? | Useful Arabic rule capture, local operating knowledge and reusable integrations | Localization becomes valuable through better accepted decisions and lower adoption effort; country targeting alone is insufficient |

Keep the earlier engineering corrections: independent validation, precise costs, preserved cargo custody, separate lifecycle/validity, revisioned snapshots, cross-scope reservations, honest timeout/partial-plan semantics and ambiguous-send handling. The Fleetline evidence strengthens the product thesis; it does not remove these requirements.

The main local uncertainties are dispatch authority, sufficient assignment flexibility, reliable starting states/costs, access to changing data and willingness to pay. Prefer a customer with several feasible choices per job and repeated changes. A fleet with permanently dedicated vehicles can match the target size while offering little optimization value.

Optimization can represent preferences, deadlines and penalties mathematically. Our design uses language models to translate and clarify company knowledge into supported rules. Public product descriptions do not justify assuming that Fleetline uses CP-SAT, that traditional solvers cannot model preferences, or that unrestricted generated solver code is required. Start with a tested rule catalogue and record unsupported requests. Repeated valuable requests become reviewed model/compiler extensions with fixtures.

## 3 The first product to prove

The initial workflow is:

1. Import a template of confirmed jobs, resource teams and existing commitments.
2. Review locations, windows, units, availability and costs; leave unresolved data visible.
3. Take an immutable snapshot with approved lane times and an explicit end-state policy.
4. Evaluate the imported dispatcher plan and a deterministic baseline.
5. Produce and independently validate a CP-SAT candidate.
6. Compare equivalent service, cost components, empty distance, assignments and exceptions.
7. Enter an Arabic or English constraint, review its exact entities/time/strength, approve it, solve again and inspect the differences.
8. Repeat with a lock, a disruption and an ambiguous/unsupported instruction; preserve existing commitments and show unresolved issues.
9. In the customer shadow increment, test one known additional job against owned capacity and expose its incremental contribution and service impact.
10. Export a labelled shadow result and record the dispatcher's acceptance or rejection reason.

Start with one depot, dedicated pickup-to-delivery jobs, fixed teams, a 48-hour decision horizon, SAR and Asia/Riyadh operational time. Preserve activities extending beyond the horizon. Tiny fixtures use fictitious sites and explicit synthetic lane values; customer trials use approved real inputs.

The first product demonstration includes real OpenAI interpretation of a supported instruction such as requiring a named truck to finish at a named site by a confirmed time. The resulting rule must change the actual solver input and, when needed, the plan. The interface shows why assignments changed and which cost/service effects follow. Arabic is part of this workflow, including mixed names and ambiguous dates, rather than only translated navigation.

A paid shadow evaluation uses a repeatable export/API update path with agreed field ownership and refresh frequency. Existing TMS execution remains authoritative. A spreadsheet adapter is a practical entry path, but its mappings, conflict handling and second/subsequent refresh must work. Measure time from data access to the first accepted recommendation, implementation hours, override reasons and unsupported rules alongside economics.

Defer generic chat, advanced document intake, decorative maps, drag/drop polish, partner procurement, automatic team changes, full historical replay and a native driver app. Include owned-capacity evaluation of a known offer in R1; defer market aggregation, negotiation and booking. Forecasts remain a useful later direction with explicit uncertainty, and cannot create confirmed freight in the base plan. Historical sample evaluation can begin early through the comparison engine with hindsight limitations labelled.

## 4 Architecture decisions

| Concern | Starting decision | Why |
| --- | --- | --- |
| Backend | Python modular monolith with FastAPI and Pydantic | One domain implementation shared by API, workers and tests |
| Persistence | PostgreSQL, SQLAlchemy and Alembic | Durable revisions, snapshots, tenant constraints and transactions |
| Optimization | OR-Tools CP-SAT behind a small planner interface | Initial assignment/sequencing formulation can use integer variables and explicit status handling |
| Validation and cost | Pure Python modules with no HTTP/ORM/CP-SAT dependency | Direct fixture testing and independent checking of solver/manual plans |
| Background work | PostgreSQL durable jobs; separate Python worker entry points | Reuse one operational datastore at pilot scale; make recovery and fencing explicit |
| Frontend | React/TypeScript with Next.js; generated OpenAPI client | Typed client and bilingual dispatcher interaction; business logic remains in Python |
| AI | OpenAI Responses API; typed rule proposals first, extraction later | Directly supports adaptive planning with reviewed operational effects |
| Travel | Operator-approved lane table first; versioned provider interface | Customer-specific heavy-truck feasibility needs defensible travel assumptions |
| Identity | Established OIDC authentication; Python enforces membership and scope | Avoid implementing a password system; auth supplier can be selected before R1 deployment |
| Local development | uv, locked Python dependencies, pytest, Ruff, type checking and Docker Compose | Reproducible setup and straightforward validation |

Pin compatible stable versions when M0/M1 are implemented and verify the OR-Tools wheel on the chosen Python interpreter and deployment platform. Do not copy an unverified latest version into the spec.

CP-SAT requires integer constraints and distinguishes feasible, optimal, unknown and infeasible results; map those outcomes without inventing a proof. [OR-Tools documentation](https://developers.google.com/optimization/cp/cp_solver).

The PostgreSQL queue is a design choice, not a claim that row locking supplies durable retries automatically. Keep claims short, perform work outside transactions, heartbeat leases, fence stale attempts and commit results idempotently. PostgreSQL documents SKIP LOCKED for queue-like use. CPU-heavy work belongs outside the request process. [PostgreSQL locking](https://www.postgresql.org/docs/current/sql-select.html), [FastAPI background work](https://fastapi.tiangolo.com/tutorial/background-tasks/).

Apply tenant-qualified foreign keys and scoped queries from M1. Add/test row-level security with a non-owner runtime role before customer data; RLS has privileged-role and table-owner exceptions. Do not treat it as a substitute for API authorization. [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).

Use ordinary polling initially. No Redis, Kafka, Kubernetes, agent framework or vector database is needed to test this product. Introduce infrastructure only for a demonstrated need. API and worker process separation does not require separate domain services or separate databases.

## 5 Concrete implementation work packages

### M0 Executable planning domain

Build one installable Python package and a CLI using synthetic JSON fixtures. Do not start with a broad set of screens or empty service scaffolds.

**Deliverables**

- Canonical types for jobs, stops, tractors, trailers, drivers, fixed teams, availability, current/future commitments, policies, lane estimates, costs, snapshots, activities and validation findings.
- Typed rules and deterministic semantics for resource unavailable, required end location/time, customer/equipment eligibility and preferred assignment. Fixtures must demonstrate each rule changing feasibility or the documented objective.
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
- Reusable mapping profiles with stable external IDs, units/timezones, field authority and refresh metadata. Obtain a real sample/update export or inspect the intended API contract when a pilot grants access; record unavailable access explicitly and keep building against the canonical fixture adapter.
- A review/commit API with idempotency keys, request hashes and optimistic version checks. CSV parser errors and conflicting reimports produce review items.
- Durable task records, leases, fencing and restart recovery. Introduce a single task implementation before adding multiple worker types.
- Database-backed unit/integration boundaries and an initial generated OpenAPI client. Reserve API paths only for implemented capabilities.

**Exit check:** Import → review → commit → second-source-refresh survives restart. Repeat import cannot duplicate logical records; a conflicting revision cannot overwrite a dispatcher correction. Tenant B cannot retrieve Tenant A's import, source or run. A reclaimed worker lease cannot let the old attempt overwrite results.

### M2A Deterministic planning checkpoint

Add CP-SAT and the smallest useful board after the domain and persistence boundaries work.

**Deliverables**

- A consistent snapshot transaction and immutable plan inputs, including baseline, policy versions, matrix values, known-at times and terminal obligations.
- Fixed-team candidate generation and sequencing: job/team assignment, service timing, sequence-dependent repositioning, availability and independent occupancy for tractor/trailer/driver. Prune only on defensible necessary conditions; compare pruning against tiny unpruned fixtures.
- Strict-complete runs with all confirmed jobs required. Offer diagnostic-partial runs explicitly after a strict failure/timeout, preserving the original outcome and total time budget. Unknown is not proven infeasible.
- Priority/service ordering, cost/churn breakdown and bounded solving. Hints and heuristic incumbents are validated against the same snapshot; they are not a feasibility guarantee.
- API endpoints for solver runs/progress/cancellation, plan detail/comparison and versioned draft edits/locks. Manual edits create a draft revision and run the same final-plan validator.
- One page with jobs, resource timeline, review issues and comparison details; persisted state and job polling. Form controls before drag/drop. Establish RTL/localized message infrastructure now.
- Tiny oracle comparisons and a benchmark report for 50 teams/150 jobs/48 hours, including actual hardware, solver settings, candidate density, coverage, validation time and end-to-end latency.

**Exit check:** A fresh checkout can run import → review → solve → validate → compare → structured-rule edit → replan. The API remains responsive while a worker solves. A timeout, cancellation or worker restart preserves previous results and records the new outcome correctly. Performance misses are reported without weakening constraints. This is an engineering checkpoint; M2B completes R0.

### M2B OpenAI rule driven replanning

Implement RuleProposal against M0's rule types. Resolve resources/sites in the current tenant, anchor relative times to an explicit operational date and timezone, distinguish hard conditions from preferences, and ask for clarification when needed. Show the exact interpretation and affected work. An authorized approval creates a rule version; the deterministic compiler changes the snapshot/model; the worker replans; the validator and comparison explain the outcome. A chat response without this chain does not complete the increment.

Use the official Python SDK's Responses parsing with Pydantic schemas. Explicitly handle refusals and incomplete responses, then run domain validation: schema correctness is not operational correctness. [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

Configure `OPENAI_API_KEY`, `OPENAI_MODEL_EXTRACTION` and `OPENAI_MODEL_RULES` in backend secrets. The founder provides the key when real calls are tested; do not put it in chat, the web client, source control or logs. The model choice follows a held-out Arabic/English evaluation and account availability; model names and pricing are not assumed by this plan.

Use `store=false` by default and minimize input data. That setting does not mean Zero Data Retention; approve the actual provider processing and file-retention configuration before customer documents are sent. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

**Exit check:** Real Arabic and English requests produce supported rules and demonstrate validated plan differences. Ambiguous and unsupported requests cannot silently activate. Provider/key failures leave manual planning usable. Report critical-field errors, review effort, latency and token usage. No model can publish or directly mutate domain state. Fixtures support offline tests, but a missing key leaves the real AI gate incomplete. This completes the R0 demonstration.

### M3 Integrated customer shadow pilot

Finish production authentication/scoped access, private source access, repeatable XLSX/TMS input updates, Arabic/English flows, freshness confirmations, baseline import, supported future-work disruptions, exports and tested restore. Use current approved lane data and policies. Record each recommendation's acceptance/rejection, correction and unsupported rule requests. Explicitly measure mapping/setup hours and data refresh lag.

Add a known offered job with price/windows and evaluate it using owned available capacity. Force service of that offer in the test scenario while preserving confirmed obligations, locks and required end states. Compare incremental cost and revenue with matching assumptions and disclosed search quality. Do not book the job, assume partner capacity or source freight from a marketplace.

**Exit check:** One dispatch team reviews recommendations on current authorized data, successfully introduces a supported rule, sees the effects of a real source update and evaluates a known offer. Exports reconcile and remain labelled shadow. Publication is disabled. Preliminary historical comparisons disclose missing known-at data; modeled gains are not claimed as realized savings.

### M4 Optional document intake

Add JobExtractionProposal for pasted text, then PDF/images if source preview and extraction evaluation are reliable. Reuse the OpenAI gateway, provenance, semantic checks and review mechanism. This can reduce intake effort but must not delay rule-driven planning or a usable integration.

**Exit check:** Reviewed source-backed fields can enter the existing import pipeline. Ambiguous critical facts remain unresolved, prompt injection has no operational effect, and manual intake remains usable during provider failures.

### M5 Supervised live dispatch

Implement exact-version approval, cross-scope reservation checks, atomic publication/outbox and the customer's selected authoritative channel. Prefer the existing TMS/driver system; a native driver app is conditional on customer need. Resolve ambiguous sends; distinguish publication, delivery and acknowledgment. Test an actual staging integration and customer operating procedures before enabling live mode.

**Exit check:** Concurrent publication, expired assumptions, worker crashes, duplicate events and old-version acknowledgments behave according to the PRD. The customer approves authority, supported disruption behavior, exception ownership and the delivery/update path. Imported live commitments constrain planning before the system starts publishing its own instructions.

### M6 Extensions and M7 repeatable rollout

Expand into partner offers, multi-offer selection, full as-of replay and uncertain-demand scenarios after the owned-capacity decision loop is useful. Keep per-revision knowledge timestamps from M1 so replay remains possible later. Measure onboarding effort, support load, compute/provider costs, dispatcher adoption and willingness to pay before expanding to another segment.

## 6 Initial acceptance mapping

This maps the major work packages to the PRD acceptance suite. Individual tests can begin earlier; a later stage must still pass all applicable earlier checks. For multi-part scenarios, record the covered subset explicitly. Extend the checklist before enabling a deferred capability.

| Work package | Primary acceptance coverage |
| --- | --- |
| M0 domain | AC-05–09, 11, 13–14, 24–25, 27, 40, 42, 46; synthetic fixed-team subset |
| M1 persistence | AC-01–02, 31, 37, 45, 49; source/import/run isolation now, other resources when introduced |
| M2A planning | AC-07–09, 11–14, 22–25, 29, 31, 35, 40, 42, 44, 46; provider outage uses an explicit test adapter |
| M2B adaptive rules | AC-03–04 for instructions, 12, 30, 36, 48, 50 plus key absence, timeout, refusal, incomplete output and semantic-error tests |
| M3 integrated shadow | AC-15–16, 26 for owned-capacity effects, 27, 30, 32, 34, 38–42, 49 plus earlier checks on customer data; publication-related parts remain disabled |
| M4 intake | AC-03–04 for source documents, extraction evaluation and manual fallback |
| M5 live | AC-17–21, 33, 35, 38–39, 43, 45; no partner quote path until that extension is enabled |
| M6 extensions | AC-10, 26 including partner effects, 28, 41, 47 and full replay/publication/partner interactions |

Avoid tests that only mirror ORM field names or mock away the invariants being checked. Use real PostgreSQL for transaction, tenant and concurrency tests, and independent expected results for costs and solver fixtures.

## 7 Customer evidence to obtain while coding

Ask a qualified operator for an approved/anonymized sample covering several ordinary operating days, ideally 5–10, including difficult days rather than only clean examples. This is a proposed discovery package, not a prerequisite for synthetic M0 work.

- Jobs, creation/known-at timestamps, pickup/delivery window meanings, equipment/cargo requirements, service durations and cancellations.
- Resource start locations, current loaded work, team pairings, availability, maintenance and relevant operating-policy history.
- Actual assignments, changes and reasons; approved lane times/distances; costs with inclusions/exclusions.
- Which system/role owns each field, how updates arrive, how often they become stale and which future assignments can change.
- Who can accept recommendations, who can authorize spending and which measurable planning problem would justify paying.
- Ten concrete dispatcher rules and recent rejected/changed assignments, written in the customer's normal Arabic/English; identify which must be supported for a useful trial.
- A second export or update sample and a walkthrough of the current system, so integration is evaluated beyond initial file loading.

Before R1, require a named dispatcher willing to review results, an approved data/update path, a supported fixed-team workflow and an agreed evaluation objective. Budget hands-on mapping and constraint reviews. Keep remote delivery as the preference, use focused calls or recorded walkthroughs, and obtain local operational help when remote evidence is inadequate. Track which customization becomes reusable and which remains ongoing service work. If the existing TMS already solves the decision problem acceptably, find a demonstrable planning gap before expanding.

The founder still needs to resolve the pilot customer, publication channel, deployment/processing requirements and pricing through actual customer evidence. None prevents starting M0. The first implementation sequence is M0 → M1 → M2A → M2B, with integration discovery alongside it. Demonstrate a dispatcher changing the plan through reviewed language and seeing a feasible revised decision with explained tradeoffs, or an explicit conflict/no-candidate result when the revised conditions cannot be satisfied by the search.
