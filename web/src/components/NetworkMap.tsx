// The network as a quiet constellation: real site positions, the lanes the plan drives.
// Geography never mirrors, so the map stays left-to-right in Arabic.
import { useMemo } from "react";
import type { Network } from "../api";
import { useI18n } from "../i18n";

const WIDTH = 620;
const HEIGHT = 490;
// Equirectangular over Saudi Arabia: about 30 px per degree.
export const project = (lat: number, lon: number): [number, number] => [Math.round((lon - 35.5) * 30), Math.round((32.3 - lat) * 30)];

function arc([ax, ay]: [number, number], [bx, by]: [number, number]): string {
  const cx = Math.round((ax + bx) / 2 - (by - ay) * 0.16);
  const cy = Math.round((ay + by) / 2 + (bx - ax) * 0.16);
  return `M${ax} ${ay} Q${cx} ${cy} ${bx} ${by}`;
}

export function NetworkMap({ network }: { network: Network }) {
  const { t, lang, count } = useI18n();
  const drawn = useMemo(() => {
    const at = new Map(network.sites.map((s) => [s.id, project(s.lat, s.lon)]));
    const busy = new Set(network.lanes.flatMap((l) => [l.from, l.to]));
    // Label each city once, at its busiest site, most important cities first; skip a
    // label that would sit too close to one already placed.
    const cityTrucks = new Map<string, number>();
    for (const s of network.sites) cityTrucks.set(s.city, (cityTrucks.get(s.city) ?? 0) + s.trucks);
    const placed: [number, number][] = [];
    const order = [...network.sites].sort(
      (a, b) => (cityTrucks.get(b.city) ?? 0) - (cityTrucks.get(a.city) ?? 0) || b.trucks - a.trucks || Number(busy.has(b.id)) - Number(busy.has(a.id)),
    );
    const labelled = new Set<string>();
    const cities = new Set<string>();
    for (const site of order) {
      const [x, y] = at.get(site.id)!;
      if (!cities.has(site.city) && placed.every(([px, py]) => Math.hypot(px - x, py - y) > 30)) {
        labelled.add(site.id);
        cities.add(site.city);
        placed.push([x, y]);
      }
    }
    const grid: [number, number][] = [];
    for (let gx = 10; gx < WIDTH; gx += 30) for (let gy = 10; gy < HEIGHT; gy += 30) grid.push([gx, gy]);
    return {
      grid,
      lanes: network.lanes.map((lane, i) => ({
        key: `${lane.from}-${lane.to}-${lane.loaded}`,
        d: arc(at.get(lane.from)!, at.get(lane.to)!),
        loaded: lane.loaded,
        width: 1.2 + Math.min(lane.trips, 6) * 0.25,
        delay: `-${(i * 0.37).toFixed(2)}s`,
      })),
      sites: network.sites.map((site, i) => {
        const [x, y] = at.get(site.id)!;
        const hub = site.trucks > 0;
        const right = x < 470;
        return { site, x, y, hub, right, labelled: labelled.has(site.id), trucks: cityTrucks.get(site.city) ?? 0, delay: `${i * 380}ms` };
      }),
    };
  }, [network]);

  return (
    <div dir="ltr" className="network-map">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={t("mapAlt")}>
        <g opacity="0.5">
          {drawn.grid.map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r="0.9" fill="var(--faint)" />
          ))}
        </g>
        {drawn.lanes.map((lane) => (
          <g key={lane.key}>
            {lane.loaded && <path d={lane.d} fill="none" stroke="var(--accent)" strokeWidth={lane.width + 5} strokeLinecap="round" opacity="0.12" />}
            <path
              className={lane.loaded ? "lane" : "lane-empty"}
              d={lane.d}
              fill="none"
              stroke={lane.loaded ? "var(--accent)" : "var(--warm)"}
              strokeWidth={lane.width}
              strokeLinecap="round"
              style={{ animationDelay: lane.delay }}
            />
          </g>
        ))}
        {drawn.sites.map(({ site, x, y, hub, right, labelled, trucks, delay }) => (
          <g key={site.id}>
            {hub && <circle className="ping" cx={x} cy={y} r="6" fill="none" stroke="var(--accent)" style={{ animationDelay: delay }} />}
            <circle cx={x} cy={y} r={hub ? 5.5 : 3} fill={hub ? "var(--text)" : "var(--muted)"} />
            {labelled && (
              <text x={right ? x + (hub ? 11 : 8) : x - (hub ? 11 : 8)} y={y + 4} textAnchor={right ? "start" : "end"} fontSize="12" fill="var(--muted)">
                {lang === "ar" ? site.city_ar : site.city}
              </text>
            )}
            {labelled && trucks > 0 && (
              <text x={right ? x + 11 : x - 11} y={y + 19} textAnchor={right ? "start" : "end"} fontSize="11" fill="var(--accent-text)">
                {count("trucks", trucks)}
              </text>
            )}
          </g>
        ))}
      </svg>
    </div>
  );
}
