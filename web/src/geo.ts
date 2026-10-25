// Geography for the maps: one projection, real coastlines and borders, real road paths.
import { useEffect, useState } from "react";

export const MAP_WIDTH = 620;
export const MAP_HEIGHT = 490;
// Equirectangular, scaled for Saudi latitudes (cos 24°), so the country keeps its shape.
export const project = (lat: number, lon: number): [number, number] => [
  Math.round((lon - 34.0) * 27.4 * 10) / 10,
  Math.round((32.6 - lat) * 30 * 10) / 10,
];

export type Region = { countries: { code: string; home: boolean; rings: [number, number][][] }[] };

let region: Promise<Region | null> | null = null;

/** Saudi Arabia and its neighbours (Natural Earth), loaded once and shared by every map. */
export function useRegion(): Region | null {
  const [value, setValue] = useState<Region | null>(null);
  useEffect(() => {
    region ??= fetch("/geo/region.json")
      .then((r) => (r.ok ? (r.json() as Promise<Region>) : null))
      .catch(() => null);
    let live = true;
    void region.then((r) => live && setValue(r));
    return () => {
      live = false;
    };
  }, []);
  return value;
}

/** SVG path data for a country's outline. */
export function outline(rings: [number, number][][]): string {
  return rings
    .map((ring) => ring.map(([lon, lat], i) => `${i ? "L" : "M"}${project(lat, lon).join(" ")}`).join("") + "Z")
    .join("");
}

/** Points of an encoded polyline (precision 5, as OSRM returns it), as [lat, lon]. */
export function decode(line: string): [number, number][] {
  const points: [number, number][] = [];
  let [index, lat, lon] = [0, 0, 0];
  while (index < line.length) {
    for (const axis of [0, 1]) {
      let [shift, result, byte] = [0, 0, 0];
      do {
        byte = line.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20);
      const delta = result & 1 ? ~(result >> 1) : result >> 1;
      if (axis === 0) lat += delta;
      else lon += delta;
    }
    points.push([lat / 1e5, lon / 1e5]);
  }
  return points;
}

/** SVG path data along a road, already projected. */
export function roadPath(points: [number, number][]): string {
  return points.map(([lat, lon], i) => `${i ? "L" : "M"}${project(lat, lon).join(" ")}`).join("");
}
