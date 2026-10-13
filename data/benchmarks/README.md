# Solver benchmarks

## `sartori_buriol/`

Sartori & Buriol, *Instances for the Pickup and Delivery Problem with Time Windows based on open data*, Mendeley Data v2, DOI [10.17632/wr2ct4r22f.2](https://data.mendeley.com/datasets/wr2ct4r22f/2).

- Downloaded 12 October 2026 through the Mendeley public API. Every file matched its published SHA-256 hash.
- Only the 100-, 200- and 400-location sets are included: 75 instances plus their best-known solutions, 4.7 MB in total. The larger sets (600–5,000 locations, about 1.3 GB) were skipped.
- File formats: `instances/README.txt` and `solutions/README.txt`.

**Not usable for our engine**, as found on 13 Oct: these are multi-load PDPTW instances (a vehicle carries several shipments at once); our engine plans full truckloads. Kept for a possible future multi-load extension.

## Not obtained

Srour et al., *MIPLIB truckload PDPTW instances derived from a real-world drayage case* ([ERS-2010-036-LIS](https://repub.eur.nl/pub/20883)): 165 instances, 40 trucks and 65 jobs per day. Only the report is public; no instance files are linked. MIPLIB was unreachable from this machine.
