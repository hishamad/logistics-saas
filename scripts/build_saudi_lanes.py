"""Build a Saudi freight-node lane matrix from OpenStreetMap road routing.

Usage: python scripts/build_saudi_lanes.py [--truck-factor 1.3]

Distances come from the public OSRM demo server (car profile on OpenStreetMap
roads). Truck durations are the car duration multiplied by --truck-factor, an
explicit assumption, not a measured heavy-vehicle speed. Coordinates are
approximate (within a few km); OSRM snaps each point to the nearest road.
Use a self-hosted OSRM/GraphHopper truck profile before relying on these
values for a customer.
"""

import argparse
import csv
import json
import urllib.request
from pathlib import Path

# Short city names for map labels (several sites can share a city).
MAP_LABELS = {
    "riyadh": ("Riyadh", "الرياض"),
    "riyadh_ind2": ("Riyadh", "الرياض"),
    "riyadh_dryport": ("Riyadh", "الرياض"),
    "kharj": ("Al-Kharj", "الخرج"),
    "sudair": ("Sudair", "سدير"),
    "dammam_port": ("Dammam", "الدمام"),
    "dammam_ind2": ("Dammam", "الدمام"),
    "jubail": ("Jubail", "الجبيل"),
    "hofuf": ("Al-Ahsa", "الأحساء"),
    "causeway": ("Causeway", "الجسر"),
    "batha": ("Al-Batha", "البطحاء"),
    "hafr": ("Hafr Al-Batin", "حفر الباطن"),
    "jeddah_port": ("Jeddah", "جدة"),
    "jeddah_ind": ("Jeddah", "جدة"),
    "kaec_port": ("KAEC", "مدينة الملك عبدالله"),
    "rabigh": ("Rabigh", "رابغ"),
    "makkah": ("Makkah", "مكة"),
    "taif": ("Taif", "الطائف"),
    "madinah": ("Madinah", "المدينة"),
    "yanbu": ("Yanbu", "ينبع"),
    "khamis": ("Khamis Mushait", "خميس مشيط"),
    "jazan": ("Jazan", "جازان"),
    "najran": ("Najran", "نجران"),
    "buraydah": ("Buraydah", "بريدة"),
    "hail": ("Hail", "حائل"),
    "tabuk": ("Tabuk", "تبوك"),
    "sakaka": ("Sakaka", "سكاكا"),
    "arar": ("Arar", "عرعر"),
}

# id, English name, Arabic name, kind, latitude, longitude
SITES = [
    ("riyadh", "Riyadh city", "الرياض", "city", 24.7136, 46.6753),
    ("riyadh_ind2", "Riyadh 2nd Industrial City", "المدينة الصناعية الثانية بالرياض", "industrial", 24.5600, 46.8700),
    ("riyadh_dryport", "Riyadh Dry Port", "ميناء الرياض الجاف", "port", 24.6700, 46.7700),
    ("kharj", "Al-Kharj", "الخرج", "city", 24.1500, 47.3000),
    ("sudair", "Sudair Industrial City", "مدينة سدير للصناعة", "industrial", 25.6700, 45.6200),
    ("dammam_port", "King Abdulaziz Port, Dammam", "ميناء الملك عبدالعزيز بالدمام", "port", 26.4900, 50.2000),
    ("dammam_ind2", "Dammam 2nd Industrial City", "المدينة الصناعية الثانية بالدمام", "industrial", 26.3000, 50.0300),
    ("jubail", "Jubail Industrial City", "الجبيل الصناعية", "industrial", 27.0000, 49.6200),
    ("hofuf", "Al-Ahsa (Hofuf)", "الأحساء", "city", 25.3800, 49.5900),
    ("causeway", "King Fahd Causeway (Saudi side)", "جسر الملك فهد", "border", 26.1800, 50.3300),
    ("batha", "Al-Batha border crossing (UAE)", "منفذ البطحاء", "border", 24.1800, 51.5500),
    ("hafr", "Hafr Al-Batin", "حفر الباطن", "city", 28.4300, 45.9700),
    ("jeddah_port", "Jeddah Islamic Port", "ميناء جدة الإسلامي", "port", 21.4700, 39.1700),
    ("jeddah_ind", "Jeddah Industrial City", "المدينة الصناعية بجدة", "industrial", 21.3900, 39.2400),
    ("kaec_port", "King Abdullah Port", "ميناء الملك عبدالله", "port", 22.5200, 39.0800),
    ("rabigh", "Rabigh", "رابغ", "industrial", 22.8000, 39.0300),
    ("makkah", "Makkah", "مكة المكرمة", "city", 21.4200, 39.8300),
    ("taif", "Taif", "الطائف", "city", 21.2700, 40.4200),
    ("madinah", "Madinah", "المدينة المنورة", "city", 24.4700, 39.6100),
    ("yanbu", "Yanbu", "ينبع", "port", 24.0900, 38.0600),
    ("khamis", "Khamis Mushait", "خميس مشيط", "city", 18.3000, 42.7300),
    ("jazan", "Jazan", "جازان", "port", 16.8900, 42.5700),
    ("najran", "Najran", "نجران", "city", 17.4900, 44.1300),
    ("buraydah", "Buraydah (Qassim)", "بريدة", "city", 26.3300, 43.9700),
    ("hail", "Hail", "حائل", "city", 27.5200, 41.6900),
    ("tabuk", "Tabuk", "تبوك", "city", 28.3800, 36.5700),
    ("sakaka", "Sakaka (Al-Jouf)", "سكاكا", "city", 29.9700, 40.2100),
    ("arar", "Arar", "عرعر", "city", 30.9800, 41.0400),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--truck-factor", type=float, default=1.3)
    parser.add_argument("--out", default="data/saudi")
    parser.add_argument(
        "--table", help="Previously fetched OSRM table JSON (e.g. downloaded with curl)"
    )
    parser.add_argument("--print-url", action="store_true")
    args = parser.parse_args()
    coords = ";".join(f"{lon},{lat}" for *_, lat, lon in SITES)
    url = f"https://router.project-osrm.org/table/v1/driving/{coords}?annotations=distance,duration"
    if args.print_url:
        print(url)
        return
    if args.table:
        table = json.loads(Path(args.table).read_text(encoding="utf-8"))
    else:
        with urllib.request.urlopen(url, timeout=60) as response:
            table = json.load(response)
    if table.get("code") != "Ok":
        raise SystemExit(f"OSRM error: {table.get('code')}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "sites.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "name_ar", "kind", "lat", "lon", "snapped_road_m", "city", "city_ar"])
        for site, snapped in zip(SITES, table["sources"], strict=True):
            writer.writerow([*site, round(snapped["distance"]), *MAP_LABELS[site[0]]])
    source = f"OSRM/OpenStreetMap car route; truck time = car x {args.truck_factor}"
    with (out / "lanes.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["from_site_id", "to_site_id", "distance_m", "duration_minutes", "source"])
        for i, a in enumerate(SITES):
            for j, b in enumerate(SITES):
                if i == j:
                    continue
                distance = table["distances"][i][j]
                duration = table["durations"][i][j]
                if distance is None or duration is None:
                    continue
                writer.writerow(
                    [a[0], b[0], round(distance), max(1, round(duration / 60 * args.truck_factor)), source]
                )
    print(f"Wrote {len(SITES)} sites and lanes to {out}")


if __name__ == "__main__":
    main()
