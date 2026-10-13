# Engine research: what the best optimization engines do, and what we should improve

*13 October 2026. Hisham + Claude. Scope: academic work on routing and truckload planning, commercial freight engines, open-source solvers. Vendor claims are marked as such; nothing here was independently verified unless stated.*

## The short version

Our engine is built in the right *shape*: a fast route simulator inside a ruin-and-recreate search, checked by an independent validator. That is also the shape of the strongest published heuristics. It falls short in four ways:

1. **We don't know how good it is.** There is no lower bound and no benchmark against published best-known solutions.
2. **It is slow and its search moves are basic.** Python, three simple removal moves, plain greedy re-insertion. The leading solvers use compiled cores, smarter moves and better acceptance rules.
3. **It is myopic.** It plans one window as if the world ended afterwards. Trucks can finish the week stranded, and an offer load is accepted if it pays more than it costs *today*, ignoring what that truck could have earned next. This is exactly where the truckload specialists (Optimal Dynamics, Optym, Fleetline) put their effort.
4. **Its inputs are rough.** Travel time is car time × 1.3, and dwell times at ports are fixed guesses. Better plans need better times more than better search.

Recommended order: measure, then strengthen the search, then teach it to look ahead. Details and evidence follow.

---

## 1 What the leaders are doing

### Truckload specialists (our direct reference points)

| Company | What they emphasise | Relevance to us |
| --- | --- | --- |
| **Fleetline** (YC S25, acquired by Optym Aug 2026) | Optimization + LLM-driven changes, weekly planning, contract + spot load mix, home time, HOS, demand forecasting. Hiring for MILP/LP/heuristics *and* "RL environments or dynamic programming at scale." ([YC](https://ycombinator.com/companies/fleetline), [job](https://www.workatastartup.com/jobs/81730)) | Their hiring signals the next step after a static optimizer: simulation and learning over time. |
| **Optym LoadAi** | Driver–load assignment, multi-day routes, spot opportunities, live re-optimization from ELD/telematics; considers load priority, home time, HOS, deadhead, broker-vs-own decisions; dispatcher can override. ([Optym](https://optym.com/truckload/loadai), [LoadOps help](https://help.loadops.com/loadai), [Motive marketplace](https://marketplace.gomotive.com/app/loadai-by-optym)) | Confirms our feature list. Their integrations do the live-data part we don't have yet. |
| **Optimal Dynamics** (from Powell's Princeton lab) | "Decision intelligence": **load acceptance** by simulating dispatching into the future, asset-vs-brokerage decisions, bid-rate analysis. ([FleetOwner](https://fleetowner.com/technology/article/21285308/optimal-dynamics-unveils-new-ai-powered-solutions-for-enhanced-truckload-operations-efficiency), [blog](https://optimaldynamics.com/resource/automating-load-level-decisions-between-the-asset-brokerage-divisions-to-maximize-network-potential)) | Their core idea, *the value of a truck at a place and time*, is what our engine is missing (§3). |
| **Uber Freight Powerloop** | Trailer pools, drop-and-hook, AI "bundling" of loads into tours; claims >30% fewer empty miles from bundles. ([Uber Freight](https://www.uberfreight.com/en-US/newsroom/uber-freight-scales-powerloop-nationally-expands-dedicated-fleets-as-demand-accelerates), [Trucking Dive](https://www.truckingdive.com/news/uber-freight-expands-drop-hook-program-powerloop-nationally/711362/)) | Shows the biggest empty-mile wins can come from *operating model* (decoupling trailers, relays), not just better routing. |

### The academic and open-source frontier

- **Hybrid genetic search (HGS) / PyVRP** is the strongest open-source family. PyVRP won the DIMACS 2021 VRPTW challenge and the static track of EURO meets NeurIPS 2022. It reports average gaps of roughly 0.25–1% to best-known solutions across classic variants. It is written in Python with a C++ core. ([paper](https://arxiv.org/pdf/2403.13795), [benchmarks](https://pyvrp.org/setup/benchmarks.html)) **Important for us:** its open-source edition supports time windows, multiple depots, optional "prize" clients (our offer loads) and shift limits, but **EU/US hours-of-service break planning is Enterprise-only.** ([pyvrp.org](https://pyvrp.org/))
- **Ruin-and-recreate done well:** SISR (Slack Induction by String Removals) removes *strings* of consecutive stops from nearby routes and re-inserts them greedily with occasional "blinks" (deliberately skipped positions). It beats many specialised methods and works for pickup-and-delivery with time windows. ([Christiaens & Vanden Berghe 2020](https://ideas.repec.org/a/inm/ortrsc/v54y2020i2p417-433.html))
- **Acceptance rules matter:** in a systematic comparison inside ALNS, record-to-record travel was "consistently undominated", alongside simulated annealing and threshold acceptance. ([Santini, Ropke & Hvattum 2018](https://ideas.repec.org/a/spr/joheur/v24y2018i5d10.1007_s10732-018-9377-x.html))
- **Hours-of-service routing is a known, solved problem class.** Goel & Irnich solved vehicle routing with truck driver scheduling to proven optimality (EU and US rules) by modelling driver activities explicitly; follow-ups use bidirectional labelling. Their key insight is that *where* you place rests (e.g. during a long wait) changes feasibility, not just when you're forced to stop. ([Goel & Irnich 2017](https://ideas.repec.org/a/inm/ortrsc/v51y2017i2p737-754.html))
- **Planning over time.** Powell's approximate dynamic programming for Schneider modelled 6,000+ drivers, matched expert dispatchers, and estimated *the marginal value of drivers by type and location*. It led to $5M/year in domicile savings and >50% fewer late deliveries. ([Simão et al. 2009](https://collaborate.princeton.edu/en/publications/an-approximate-dynamic-programming-algorithm-for-large-scale-flee/))
- **Anticipating uncertain demand.** Sample plausible future loads, solve each scenario, and commit only to decisions most scenarios agree on (Bent & Van Hentenryck's multiple-scenario approach). The gains grow as the share of not-yet-known work rises. Cheaper "anticipatory insertion" often matches it when dynamism is low. ([Bent & Van Hentenryck 2004](https://pubsonline.informs.org/doi/fpi/10.1287/opre.1040.0124), [comparison](https://myweb.uiowa.edu/bthoa/myweb_bthoa/Research_files/DTSP_rev4_03May11.pdf))
- **Machine learning + optimization.** The EURO meets NeurIPS 2022 dynamic track was won by an ML model that drives an optimization layer, not by pure RL. ([competition paper](https://proceedings.mlr.press/v220/kool23a.html)) Surveys agree that end-to-end neural solvers are fast but "can hardly beat cutting-edge heuristics". ([survey](https://arxiv.org/pdf/2303.04147))
- **Load acceptance with opportunity cost.** Accept or reject a tender, accounting for what the truck could earn next. Lines of work include RL for broker pricing ([Wang, Nascimento & Powell](https://arxiv.org/pdf/1802.08976)), plus 2026 preprints on dual-price acceptance policies with certified gaps and a public benchmark ([FreightBidBench](https://arxiv.org/abs/2607.07343)). These are recent and not peer-reviewed.
- **LLMs.** Three distinct uses:
  - **Translating language into models** (OptiMUS). It works but struggles with ambiguity and code quality, which supports our *typed-rule catalogue* design over free-form model writing. ([OptiMUS](https://arxiv.org/html/2407.19633v3))
  - **Explaining results and answering what-ifs** by re-running the real solver, without the LLM doing the math (Microsoft OptiGuide). ([paper](https://arxiv.org/pdf/2307.03875v1))
  - **Evolving heuristics automatically** (FunSearch, EoH, ReEvo, VRPAgent, PyVRP+). VRPAgent reports LLM-discovered destroy/repair operators beating hand-crafted ones on CVRP, VRPTW and prize-collecting VRP. This is research-stage, but it fits an LNS like ours. ([EoH](https://arxiv.org/pdf/2401.02051), [VRPAgent](https://arxiv.org/html/2510.07073v1), [PyVRP+](https://arxiv.org/pdf/2604.07872))
- **Re-planning without chaos.** Production planning calls unstable re-plans "nervousness". Routing practice uses commitment/freeze horizons and penalties for changing what was already communicated. ([commitment horizons](https://arxiv.org/pdf/2608.13799), [consistent VRP](https://www.gerad.ca/papers/G-2023-14.pdf))
- **Better inputs.** Industry ETA systems use a map baseline plus an ML model of residual delay (dwell, carrier behaviour, disruptions) ([project44](https://www.project44.com/?p=72833)). Time-dependent travel (rush hours) changes routing decisions measurably. ([Figliozzi](https://trec.pdx.edu/research/project/133/))
- **Testing decision models safely.** Run the candidate engine in *shadow* next to the live process, then *switchback* (alternate engines by time or region) before promoting it. ([Nextmv](https://www.nextmv.io/blog/introducing-switchback-testing-a-b-testing-for-decision-models-with-network-effects), [docs](https://docs.nextmv.io/learn/experiments/))

---

## 2 Where our engine stands

| Capability | Leaders | Us today |
| --- | --- | --- |
| Search method | HGS / SISR-style LNS, compiled cores, millions of moves | LNS in pure Python, ~2,500 iterations/min on 100 trucks |
| Quality measurement | Gaps to best-known solutions and lower bounds | None: "better than greedy" only |
| Driver hours | Optimal rest placement (Goel), EU/US rule sets | Greedy rests when forced; rules unverified for KSA |
| End of horizon | Value of a truck at a place and time (ADP) | Ignored: trucks may end anywhere at no cost |
| Load acceptance | Opportunity cost, simulated future | Accept if revenue > incremental cost now |
| Uncertain demand | Scenario sampling, forecasts | Only known jobs |
| Re-planning | Freeze windows, change penalties, live data | One-shot plans; locks exist but no change penalty |
| Travel and dwell times | Truck-specific, time-dependent, learned | Car time × 1.3, fixed dwell guesses |
| Operating model | Trailer pools, relays, drop-and-hook | Fixed tractor+trailer+driver teams |
| LLM use | Constraint capture, explanations, what-ifs | Typed rule capture (parked), no explanations |

---

## 3 What we should improve, in order

### Step A — Measure before improving (≈ 1 week)
- **A benchmark harness:** fixed scenarios (pilot, full, plus 10 randomized seeds), fixed time budgets, results logged to a file we commit. Every engine change must beat it.
- **A lower bound** for full-truckload planning: an LP relaxation of "which job follows which on which truck" (an assignment/flow model) tells us how far from optimal we might be. Today we can't say if we're 2% or 20% off.
- **Calibrate on public benchmarks:** run our search core on the Sartori–Buriol instances we downloaded (without our Saudi rules) against their published best-known solutions.

### Step B — A stronger, faster search (≈ 2–3 weeks)
- **Smarter moves:** SISR string removal, regret insertion (place the hardest job first), adaptive operator weights.
- **Better acceptance:** record-to-record travel in place of our simple annealing.
- **Speed:** move the route simulator to compiled code (Rust or C++ with a Python wrapper, like PyVRP), and add incremental evaluation so a change re-checks only the part of the route it touches. Target: 10–50× more iterations in the same 60 seconds.
- **Smarter rest placement:** when a route fails on time, try taking the daily rest *earlier*, e.g. during a long wait at a port. This is the core lesson from the hours-of-service literature, and it will rescue jobs we currently call impossible.
- **Not now:** switching to PyVRP as our core. Its open-source edition lacks hours-of-service breaks and days off at home, which are central for us. We copy its architecture, not its code.

### Step C — Look ahead: the "Fleetline-beater" (≈ 3–4 weeks)
- **Value of a truck at a place and time:** estimate, by simulating future weeks, how much a truck in Riyadh on Thursday evening is worth compared with one in Dammam. Add that value at the end of the plan, so the engine stops stranding trucks and naturally prefers repositioning towards freight.
- **Opportunity-cost load acceptance:** an offer load is worth taking only if its revenue beats both its cost *and* what the truck loses by not being somewhere better. The value estimates from the first point give this almost for free.
- **Sampled future demand:** add likely backhauls (from history, or for now from our generator's lane weights) as uncertain jobs, plan several scenarios, and keep the near-term decisions most scenarios agree on.

### Step D — Re-planning dispatchers can live with (≈ 2 weeks; needed for any pilot)
- A freeze window: nothing in the next N hours changes without approval.
- A penalty for changing an already communicated assignment, so the engine only moves work when the saving is real.
- A "what changed and why" diff between plan versions.

### Step E — The AI layer, used where it actually helps
- **Explanations and what-ifs** (OptiGuide pattern): "Why does truck DMM-012 take SA-26369?", "What if we drop this job?" The solver re-runs, and the LLM only explains the computed difference. Cheap, and very strong in demos.
- **Rule capture:** keep the typed catalogue and extend it from real dispatcher requests (already designed in `ai.py`).
- **Later, offline:** LLM-evolved operators (EoH/VRPAgent style), tuned against our Step A benchmark.

### Step F — Better inputs (with the first carrier's data)
- Truck-specific, time-dependent travel times (Riyadh rush hours, weekend patterns), and learned dwell times per site, especially ports.
- Driving-hour rules confirmed against current TGA regulation.

### Later, and only with a customer who wants it
- **Decoupling tractors and trailers** (trailer pools, relays, drop-and-hook). Potentially the biggest empty-mile lever (Uber Freight claims ~30%), but it changes how the carrier operates.
- **Shadow and switchback testing** in production, as the bridge from pilot to live use.

## What we deliberately won't do yet
- **End-to-end neural or deep-RL solvers.** They don't beat strong heuristics and need data and simulators we don't have.
- **Commercial solvers** (Gurobi, Hexaly). Not needed at our scale. The bound in Step A can use the free solver we already ship with (OR-Tools).
- **Generic AI chat.**

## Biggest unknowns
- Whether real Saudi carriers have enough flexibility (spare trucks, backhaul options) for look-ahead to pay off. Only real data answers this.
- How good our engine really is. Step A answers this within a week.
