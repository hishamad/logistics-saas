# Engine benchmark

Latest run: 2026-10-13 18:00 UTC · commit `00fdcff` · AMD64 Family 23 Model 113 Stepping 0, AuthenticAMD, 16 logical CPUs · `scripts/benchmark.py`. Raw results: [2026-10-13-00fdcff.json](2026-10-13-00fdcff.json).

**Exact gap**: engine cost vs CP-SAT's proven optimum on small scenarios (6 trucks, 48 h, classic rules; jobs that cannot all be served together are removed first, so both solve the identical problem). CP-SAT's model has no driving-hours rules, so this calibrates the search, not the realistic rules. **Gap vs bound**: an upper limit on how far a plan can be from optimal for the jobs it serves; the true gap is smaller.

Reading the numbers: the bound ignores waiting, rests and trips home, so it is loose. On the small cases, where the optimum is known, compare the exact gap with the gap vs bound to see how loose it is. Treat large-scenario bound gaps as a ceiling, and compare engine versions by cost on the same seeds.

## Small scenarios with a proven optimum

| Case | Jobs | CP-SAT | Optimum (SAR) | Engine (SAR) | Exact gap | Gap vs bound |
| --- | --- | --- | --- | --- | --- | --- |
| exact-1 | 10 | optimal | 8,487 | 8,487 | 0.00% | 18.4% |
| exact-2 | 11 | optimal | 21,941 | 21,941 | 0.00% | 17.8% |
| exact-3 | 11 | optimal | 24,262 | 24,262 | 0.00% | 12.0% |
| exact-4 | 6 | optimal | 9,370 | 9,370 | 0.00% | 9.8% |
| exact-5 | 5 | feasible | 5,313 | 5,313 | — | 31.7% |

## Committed scenarios

| Scenario | Run | Served | Offers | Empty | Cost (SAR) | Contribution (SAR) | Revenue/truck-day | Gap vs bound | Iterations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pilot | seed 1 | 55/56 | 14/14 | 39.4% | 92,230 | 163,701 | 3,199 | 18.2% | 47,469 |
| pilot | seed 2 | 55/56 | 14/14 | 39.4% | 92,206 | 163,725 | 3,199 | 18.1% | 46,021 |
| pilot | seed 3 | 55/56 | 14/14 | 39.4% | 92,221 | 163,710 | 3,199 | 18.2% | 46,538 |
| pilot | confirmed only | 55/56 | 0/0 | 45.7% | 77,200 | 134,143 | 2,642 | 18.6% | 48,496 |
| pilot | old greedy, confirmed only | 55/56 | 0/0 | 47.5% | 81,682 | 129,661 | 2,642 | 23.1% | — |
| full | seed 1 | 464/490 | 58/122 | 29.3% | 539,062 | 1,339,823 | 2,684 | 12.0% | 6,799 |
| full | seed 2 | 464/490 | 60/122 | 30.0% | 540,567 | 1,329,036 | 2,671 | 12.1% | 6,736 |
| full | confirmed only | 466/490 | 0/0 | 32.6% | 495,352 | 1,226,790 | 2,460 | 9.6% | 8,800 |
