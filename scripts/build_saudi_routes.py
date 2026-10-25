"""Fetch the road path between every pair of network sites, for maps.

Usage: python scripts/build_saudi_routes.py

One request per site pair to the public OSRM demo server (car profile on
OpenStreetMap roads), at most one per second as its usage policy asks. Each
path is OSRM's simplified overview as an encoded polyline (precision 5). Paths
are stored once per pair; the reverse direction is the same road, reversed.
Only for drawing: distances and times come from lanes.csv. A self-hosted OSRM
should replace the demo server before this is rebuilt routinely.
"""

import csv
import json
import ssl
import time
import urllib.request
from pathlib import Path

try:  # a maintained CA bundle; some systems' own stores miss newer certificate chains
    import certifi

    TLS = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    TLS = ssl.create_default_context()

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "data" / "saudi" / "sites.csv"
ROUTES = ROOT / "data" / "saudi" / "routes.csv"
SERVER = "https://router.project-osrm.org/route/v1/driving"


def main() -> None:
    with SITES.open(encoding="utf-8") as f:
        sites = [(r["id"], float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)]
    done: dict[tuple[str, str], str] = {}
    if ROUTES.exists():  # resume an interrupted run
        with ROUTES.open(encoding="utf-8") as f:
            done = {(r["from"], r["to"]): r["polyline"] for r in csv.DictReader(f)}
    pairs = [(a, b) for i, a in enumerate(sites) for b in sites[i + 1 :]]
    for n, ((a, alat, alon), (b, blat, blon)) in enumerate(pairs, 1):
        if (a, b) in done:
            continue
        url = f"{SERVER}/{alon},{alat};{blon},{blat}?overview=simplified&geometries=polyline"
        request = urllib.request.Request(url, headers={"User-Agent": "madar-map-build/1.0"})
        with urllib.request.urlopen(request, timeout=60, context=TLS) as response:
            answer = json.load(response)
        if answer.get("code") != "Ok":
            raise SystemExit(f"OSRM error for {a}-{b}: {answer.get('code')}")
        done[(a, b)] = answer["routes"][0]["geometry"]
        write(done)
        print(f"{n}/{len(pairs)} {a} - {b}", flush=True)
        time.sleep(1.1)
    write(done)
    print(f"{len(done)} road paths in {ROUTES.relative_to(ROOT)}")


def write(paths: dict[tuple[str, str], str]) -> None:
    with ROUTES.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\r\n")
        writer.writerow(["from", "to", "polyline"])
        for (a, b), line in sorted(paths.items()):
            writer.writerow([a, b, line])


if __name__ == "__main__":
    main()
