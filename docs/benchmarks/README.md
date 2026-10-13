# Engine benchmark

Latest run: 2026-10-13 17:35 UTC · commit `36b8229` · AMD64 Family 23 Model 113 Stepping 0, AuthenticAMD, 16 logical CPUs · `scripts/benchmark.py`. Raw results: [2026-10-13-36b8229.json](2026-10-13-36b8229.json).

**Exact gap**: engine cost vs CP-SAT's proven optimum on small scenarios (6 trucks, 48 h, classic rules; jobs that cannot all be served together are removed first, so both solve the identical problem). CP-SAT's model has no driving-hours rules, so this calibrates the search, not the realistic rules. **Gap vs bound**: an upper limit on how far a plan can be from optimal for the jobs it serves; the true gap is smaller.

Reading the numbers: the bound ignores waiting, rests and trips home, so it is loose. On the small cases, where the optimum is known, compare the exact gap with the gap vs bound to see how loose it is. Treat large-scenario bound gaps as a ceiling, and compare engine versions by cost on the same seeds.

## Small scenarios with a proven optimum

| Case | Jobs | CP-SAT | Optimum (SAR) | Engine (SAR) | Exact gap | Gap vs bound |
| --- | --- | --- | --- | --- | --- | --- |
| exact-1 | 10 | optimal | 8,487 | 9,048 | 6.61% | 23.5% |
| exact-2 | 11 | optimal | 21,941 | 22,530 | 2.68% | 19.9% |
| exact-3 | 11 | optimal | 24,262 | 24,621 | 1.48% | 13.3% |
| exact-4 | 6 | optimal | 9,370 | 9,572 | 2.16% | 11.7% |
| exact-5 | 5 | feasible | 5,313 | 5,332 | — | 32.0% |

## Committed scenarios

| Scenario | Run | Served | Offers | Empty | Cost (SAR) | Contribution (SAR) | Revenue/truck-day | Gap vs bound | Iterations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pilot | seed 1 | 55/56 | 14/14 | 39.4% | 93,691 | 162,240 | 3,199 | 19.4% | 42,970 |
| pilot | seed 2 | 55/56 | 14/14 | 39.5% | 93,681 | 162,250 | 3,199 | 19.4% | 41,896 |
| pilot | seed 3 | 55/56 | 14/14 | 39.5% | 93,693 | 162,238 | 3,199 | 19.4% | 41,665 |
| pilot | confirmed only | 55/56 | 0/0 | 45.9% | 78,543 | 132,800 | 2,642 | 20.0% | 42,479 |
| pilot | old greedy, confirmed only | 55/56 | 0/0 | 47.5% | 81,682 | 129,661 | 2,642 | 23.1% | — |
| full | seed 1 | 463/490 | 49/122 | 29.8% | 535,155 | 1,314,767 | 2,643 | 12.4% | 2,661 |
| full | seed 2 | 460/490 | 58/122 | 29.8% | 533,115 | 1,310,432 | 2,634 | 12.7% | 2,714 |
| full | confirmed only | 465/490 | 0/0 | 33.4% | 505,251 | 1,234,635 | 2,486 | 10.9% | 2,995 |
