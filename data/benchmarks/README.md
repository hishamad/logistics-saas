# Solver benchmarks

## `sartori_buriol/`

Sartori & Buriol, *Instances for the Pickup and Delivery Problem with Time Windows based on open data*, Mendeley Data v2, DOI [10.17632/wr2ct4r22f.2](https://data.mendeley.com/datasets/wr2ct4r22f/2).

- Downloaded 12 October 2026 through the Mendeley public API. Every file matched its published SHA-256 hash.
- Only the 100-, 200- and 400-location sets are included: 75 instances plus their best-known solutions, 4.7 MB in total. The larger sets (600–5,000 locations, about 1.3 GB) were skipped.
- File formats: `instances/README.txt` and `solutions/README.txt`.

These are general PDPTW instances (capacitated, multi-stop), not full truckload. Use them to check route-construction and search quality against published best-known solutions. Use `data/saudi/scenarios/` for the product's own full-truckload problem.

## Not obtained

Srour et al., *MIPLIB truckload PDPTW instances derived from a real-world drayage case* ([ERS-2010-036-LIS](https://repub.eur.nl/pub/20883)): 165 instances, 40 trucks and 65 jobs per day. Only the report is public; no instance files are linked. MIPLIB was unreachable from this machine.
