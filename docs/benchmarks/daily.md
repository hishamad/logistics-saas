# Daily rolling re-planning: policy comparison

`scripts/daily.py --seconds 15`: the full scenario (100 trucks, 7 days), planned every morning for 48 h with only the jobs known by then, then executed for one day. Mean ± sd over search seeds [1, 2, 3]. Contribution counts executed work only.

| Policy | Valid days | Confirmed served | Offers executed | Contribution (SAR) | Empty km | Changed after drivers were told |
| --- | --- | --- | --- | --- | --- | --- |
| free | 7 ± 0 | 468 ± 3 | 72 ± 6 | 1,406,346 ± 11,118 | 94,435 ± 2,324 | 221 ± 7 |
| penalty only | 7 ± 0 | 469 ± 3 | 72 ± 3 | 1,408,984 ± 17,634 | 96,825 ± 2,932 | 91 ± 9 |
| freeze 6 h | 7 ± 0 | 465 ± 2 | 72 ± 3 | 1,404,496 ± 15,634 | 93,257 ± 2,296 | 54 ± 5 |
| calm | 7 ± 0 | 459 ± 3 | 72 ± 7 | 1,399,155 ± 15,596 | 90,661 ± 3,601 | 21 ± 3 |
| lookahead | 7 ± 0 | 461 ± 3 | 68 ± 6 | 1,391,261 ± 15,869 | 94,443 ± 1,492 | 21 ± 3 |

Simplifications: plans are executed exactly (no breakdowns or delays), and drivers start each morning's plan rested (driving hours are not carried across days).
