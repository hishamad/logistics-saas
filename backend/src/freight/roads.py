"""Road paths between network sites, for drawing maps (never for distances or times).

``data/saudi/routes.csv`` holds one OpenStreetMap road path per site pair as an
encoded polyline (see scripts/build_saudi_routes.py); the other direction is the
same road reversed.
"""

import csv
from functools import lru_cache
from pathlib import Path

from freight.onboarding import NETWORK


@lru_cache
def _paths(folder: Path = NETWORK) -> dict[tuple[str, str], str]:
    file = folder / "routes.csv"
    if not file.exists():
        return {}
    with file.open(encoding="utf-8") as f:
        return {(r["from"], r["to"]): r["polyline"] for r in csv.DictReader(f)}


def road(start: str, end: str) -> str | None:
    """The road from ``start`` to ``end`` as an encoded polyline, if the network has it."""
    paths = _paths()
    if (start, end) in paths:
        return paths[(start, end)]
    if (end, start) in paths:
        return encode(decode(paths[(end, start)])[::-1])
    return None


def roads(pairs: set[tuple[str, str]]) -> dict[str, str]:
    """Roads for the (from, to) pairs that have one, keyed ``"from|to"``."""
    found = {f"{a}|{b}": road(a, b) for a, b in pairs if a != b}
    return {key: line for key, line in found.items() if line}


def decode(line: str) -> list[tuple[int, int]]:
    """Polyline (precision 5) to points in 1e-5 degrees, exact so re-encoding is lossless."""
    points: list[tuple[int, int]] = []
    index = lat = lon = 0
    while index < len(line):
        values = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(line[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            values.append(~(result >> 1) if result & 1 else result >> 1)
        lat += values[0]
        lon += values[1]
        points.append((lat, lon))
    return points


def encode(points: list[tuple[int, int]]) -> str:
    out: list[str] = []
    previous = (0, 0)
    for point in points:
        for value, last in zip(point, previous, strict=True):
            delta = value - last
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                out.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            out.append(chr(delta + 63))
        previous = point
    return "".join(out)
