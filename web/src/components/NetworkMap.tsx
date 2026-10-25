// The network on the real map: coast and borders, the roads the latest plan drives,
// and the sites. Geography never mirrors, so the map stays left-to-right in Arabic.
import { Minus, Plus, RotateCcw } from "lucide-react";
import { useMemo } from "react";
import type { Network } from "../api";
import { decode, MAP_HEIGHT, MAP_WIDTH, outline, project, roadPath, useRegion } from "../geo";
import { useI18n } from "../i18n";
import { usePanZoom } from "./usePanZoom";

// A gentle curve where no road path is known (a site outside the road data).
function arc([ax, ay]: [number, number], [bx, by]: [number, number]): string {
  const cx = Math.round((ax + bx) / 2 - (by - ay) * 0.16);
  const cy = Math.round((ay + by) / 2 + (bx - ax) * 0.16);
  return `M${ax} ${ay} Q${cx} ${cy} ${bx} ${by}`;
}

export function NetworkMap({ network }: { network: Network }) {
  const { t, lang, count } = useI18n();
  const region = useRegion();
  const map = usePanZoom(MAP_WIDTH, MAP_HEIGHT);
  const u = map.scale; // marks keep their size on screen at any zoom

  const land = useMemo(() => region?.countries.map((c) => ({ code: c.code, home: c.home, d: outline(c.rings) })) ?? [], [region]);
  const drawn = useMemo(() => {
    const at = new Map(network.sites.map((s) => [s.id, project(s.lat, s.lon)]));
    const busy = new Set(network.lanes.flatMap((l) => [l.from, l.to]));
    const cityTrucks = new Map<string, number>();
    for (const s of network.sites) cityTrucks.set(s.city, (cityTrucks.get(s.city) ?? 0) + s.trucks);
    // Most important cities first, so their names win when labels would collide.
    const order = [...network.sites].sort(
      (a, b) => (cityTrucks.get(b.city) ?? 0) - (cityTrucks.get(a.city) ?? 0) || b.trucks - a.trucks || Number(busy.has(b.id)) - Number(busy.has(a.id)),
    );
    return {
      lanes: network.lanes.map((lane, i) => {
        const road = network.roads?.[`${lane.from}|${lane.to}`];
        return {
          key: `${lane.from}-${lane.to}-${lane.loaded}`,
          d: road ? roadPath(decode(road)) : arc(at.get(lane.from)!, at.get(lane.to)!),
          loaded: lane.loaded,
          width: 1.2 + Math.min(lane.trips, 6) * 0.25,
          delay: `-${(i * 0.37).toFixed(2)}s`,
        };
      }),
      order,
      cityTrucks,
      sites: network.sites.map((site, i) => ({ site, at: at.get(site.id)!, hub: site.trucks > 0, delay: `${i * 380}ms` })),
    };
  }, [network]);

  // Label each city once, at its busiest site; skip a label too close to one already
  // placed. Zooming in makes room, so more names appear.
  const labels = useMemo(() => {
    const placed: [number, number][] = [];
    const cities = new Set<string>();
    const result = new Map<string, number>();
    for (const site of drawn.order) {
      const [x, y] = project(site.lat, site.lon);
      if (cities.has(site.city) || placed.some(([px, py]) => Math.hypot(px - x, py - y) < 30 * u)) continue;
      cities.add(site.city);
      placed.push([x, y]);
      result.set(site.id, drawn.cityTrucks.get(site.city) ?? 0);
    }
    return result;
  }, [drawn, u]);

  const { x, y, w, h } = map.view;
  return (
    <div dir="ltr" className="network-map">
      <svg
        ref={map.svg}
        viewBox={`${x} ${y} ${w} ${h}`}
        role="img"
        aria-label={t("mapAlt")}
        className={map.zoomed ? "zoomed" : undefined}
        {...map.handlers}
      >
        <g className="land">
          {land.map((c) => (
            <path key={c.code} d={c.d} className={c.home ? "land-home" : "land-other"} vectorEffect="non-scaling-stroke" />
          ))}
        </g>
        {drawn.lanes.map((lane) => (
          <g key={lane.key}>
            {lane.loaded && (
              <path d={lane.d} fill="none" stroke="var(--accent)" strokeWidth={lane.width + 5} strokeLinecap="round" strokeLinejoin="round" opacity="0.12" vectorEffect="non-scaling-stroke" />
            )}
            <path
              className={lane.loaded ? "lane" : "lane-empty"}
              d={lane.d}
              fill="none"
              stroke={lane.loaded ? "var(--accent)" : "var(--warm)"}
              strokeWidth={lane.width}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
              style={{ animationDelay: lane.delay }}
            />
          </g>
        ))}
        {drawn.sites.map(({ site, at: [sx, sy], hub, delay }) => {
          const trucks = labels.get(site.id);
          const right = sx < x + w * 0.76;
          const gap = (hub ? 11 : 8) * u;
          return (
            <g key={site.id}>
              {hub && <circle className="ping" cx={sx} cy={sy} r={6 * u} fill="none" stroke="var(--accent)" strokeWidth={u} style={{ animationDelay: delay }} />}
              <circle cx={sx} cy={sy} r={(hub ? 5.5 : 3) * u} fill={hub ? "var(--text)" : "var(--muted)"} />
              {trucks !== undefined && (
                <text
                  x={right ? sx + gap : sx - gap}
                  y={sy + 4 * u}
                  textAnchor={right ? "start" : "end"}
                  fontSize={12 * u}
                  fill="var(--muted)"
                  className="map-label"
                  strokeWidth={3 * u}
                >
                  {lang === "ar" ? site.city_ar : site.city}
                </text>
              )}
              {trucks !== undefined && trucks > 0 && (
                <text x={right ? sx + 11 * u : sx - 11 * u} y={sy + 19 * u} textAnchor={right ? "start" : "end"} fontSize={11 * u} fill="var(--accent-text)" className="map-label" strokeWidth={3 * u}>
                  {count("trucks", trucks)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="map-zoom" role="group" aria-label={t("mapZoom")}>
        <button type="button" onClick={map.zoomIn} aria-label={t("zoomIn")}>
          <Plus size={15} aria-hidden />
        </button>
        <button type="button" onClick={map.zoomOut} aria-label={t("zoomOut")} disabled={!map.zoomed}>
          <Minus size={15} aria-hidden />
        </button>
        {map.zoomed && (
          <button type="button" onClick={map.reset} aria-label={t("zoomReset")}>
            <RotateCcw size={14} aria-hidden />
          </button>
        )}
      </div>
    </div>
  );
}
