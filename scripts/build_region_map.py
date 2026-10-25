"""Cut Saudi Arabia and its neighbours out of Natural Earth country shapes, for maps.

Usage: python scripts/build_region_map.py <ne_50m_admin_0_countries.geojson> web/public/geo/region.json

The input is Natural Earth's public-domain 1:50m admin-0 countries, e.g. from
https://github.com/nvkelso/natural-earth-vector (geojson/). Clips to the region,
simplifies (Douglas-Peucker) and rounds to 3 decimals, so the app ships ~40 KB.
"""

import json
import sys

WEST, SOUTH, EAST, NORTH = 33.0, 14.5, 58.0, 34.0
TOLERANCE = 0.006  # degrees, about 650 m


def clip(ring):
    """Sutherland-Hodgman against the region's rectangle."""
    edges = [
        (lambda p: p[0] >= WEST, lambda a, b: cross_x(a, b, WEST)),
        (lambda p: p[0] <= EAST, lambda a, b: cross_x(a, b, EAST)),
        (lambda p: p[1] >= SOUTH, lambda a, b: cross_y(a, b, SOUTH)),
        (lambda p: p[1] <= NORTH, lambda a, b: cross_y(a, b, NORTH)),
    ]
    points = ring
    for inside, cut in edges:
        if not points:
            break
        out = []
        for i, current in enumerate(points):
            previous = points[i - 1]
            if inside(current):
                if not inside(previous):
                    out.append(cut(previous, current))
                out.append(current)
            elif inside(previous):
                out.append(cut(previous, current))
        points = out
    return points


def cross_x(a, b, x):
    t = (x - a[0]) / (b[0] - a[0])
    return [x, a[1] + t * (b[1] - a[1])]


def cross_y(a, b, y):
    t = (y - a[1]) / (b[1] - a[1])
    return [a[0] + t * (b[0] - a[0]), y]


def simplify(points):
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        ax, ay = points[first]
        bx, by = points[last]
        length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 or 1e-12
        best, index = 0.0, -1
        for i in range(first + 1, last):
            px, py = points[i]
            d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
            if d > best:
                best, index = d, i
        if best > TOLERANCE:
            keep[index] = True
            stack += [(first, index), (index, last)]
    return [p for p, k in zip(points, keep) if k]


def main():
    source, target = sys.argv[1], sys.argv[2]
    with open(source, encoding="utf-8") as f:
        countries = json.load(f)["features"]
    shapes = []
    for country in countries:
        geometry = country["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        rings = []
        for polygon in polygons:
            outer = clip(polygon[0])  # holes are not needed at this scale
            # A closed ring ends where it starts: simplify it open, then close it again.
            if outer and outer[0] == outer[-1]:
                outer = outer[:-1]
            outer = simplify(outer)
            outer = outer + outer[:1]
            if len(outer) >= 4:
                rings.append([[round(x, 3), round(y, 3)] for x, y in outer])
        if rings:
            code = country["properties"]["ADM0_A3"]
            shapes.append({"code": code, "home": code == "SAU", "rings": rings})
    with open(target, "w", encoding="utf-8") as f:
        json.dump(
            {"source": "Natural Earth 1:50m admin-0 countries (public domain), clipped and simplified", "box": [WEST, SOUTH, EAST, NORTH], "countries": shapes},
            f,
            separators=(",", ":"),
        )
    print(len(shapes), "countries:", " ".join(s["code"] for s in shapes))


if __name__ == "__main__":
    main()
