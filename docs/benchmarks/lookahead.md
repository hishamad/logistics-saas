# Look-ahead: two-week rolling test

`scripts/rolling.py --seconds 30`. Week 1 is the full scenario, planned myopically or with look-ahead. Week 2 has new jobs (demand seeds [43, 44]) and starts from wherever week 1 left each truck. It is planned myopically 4 times per demand seed with different search seeds, because a single run is too noisy to compare.

| Policy | Week 1 contribution | Week 1 confirmed served | Week 2 contribution, mean ± sd | Two-week total |
| --- | --- | --- | --- | --- |
| myopic | 1,311,441 | 460/490 | 1,211,244 ± 48,613 (n=8) | **2,522,685** |
| lookahead | 1,308,330 | 456/490 | 1,202,715 ± 46,264 (n=8) | **2,511,045** |

Week-2 difference (look-ahead minus myopic): SAR -8,529 ± 23,727 (one standard error). Not significant at about two standard errors.
