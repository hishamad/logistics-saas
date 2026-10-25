// One truck's route on the real map: numbered stops in the order it reaches them,
// loaded legs in the accent, empty legs dashed. Framed to the route, never mirrored.
// Sites in one city (a port and an industrial city) share a stop; the short hops
// between them are too small to draw.
import { useMemo } from "react";
import type { Board, BoardTeam } from "../api";
import { useI18n } from "../i18n";
import { project } from "./NetworkMap";

const ASPECT = 16 / 10;
type Box = [number, number, number, number]; // left, top, right, bottom
const overlaps = (a: Box, b: Box) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
const PIXELS = 340; // roughly how wide the map is drawn; keeps marks the same size at any zoom

function bend([ax, ay]: [number, number], [bx, by]: [number, number]): string {
  const cx = (ax + bx) / 2 - (by - ay) * 0.18;
  const cy = (ay + by) / 2 + (bx - ax) * 0.18;
  return `M${ax} ${ay} Q${cx.toFixed(1)} ${cy.toFixed(1)} ${bx} ${by}`;
}

export function RouteMap({ board, team }: { board: Board; team: BoardTeam }) {
  const { t, lang } = useI18n();
  const drawn = useMemo(() => {
    const geo = board.geo ?? {};
    const city = (id: string) => geo[id]?.[2];
    const drives = team.acts.filter((a) => (a[8] === "loaded" || a[8] === "empty") && a[4] !== a[5]);
    const visits = [team.depot, ...drives.map((a) => a[5])];
    if (visits.some((id) => !geo[id])) return null; // a site the map does not know
    const stops: { id: string; city: string; n: number; x: number; y: number }[] = [];
    for (const id of visits) {
      if (stops.some((s) => s.city === city(id))) continue;
      const [x, y] = project(geo[id][0], geo[id][1]);
      stops.push({ id, city: city(id)!, n: stops.length + 1, x, y });
    }
    const stop = (id: string) => stops.find((s) => s.city === city(id))!;
    const legs = drives
      .map((a, i) => ({ key: i, from: stop(a[4]), to: stop(a[5]), loaded: a[8] === "loaded" }))
      .filter((leg) => leg.from !== leg.to)
      .map((leg, i) => ({ ...leg, key: i, d: bend([leg.from.x, leg.from.y], [leg.to.x, leg.to.y]) }));
    // Frame the route with some room around it, at a fixed aspect ratio.
    const xs = stops.map((s) => s.x);
    const ys = stops.map((s) => s.y);
    const pad = Math.max(36, 0.16 * Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)));
    let [x0, x1, y0, y1] = [Math.min(...xs) - pad, Math.max(...xs) + pad, Math.min(...ys) - pad, Math.max(...ys) + pad];
    let w = Math.max(x1 - x0, 170);
    let h = Math.max(y1 - y0, 106);
    if (w / h < ASPECT) w = h * ASPECT;
    else h = w / ASPECT;
    x0 = (x0 + x1) / 2 - w / 2;
    y0 = (y0 + y1) / 2 - h / 2;
    x1 = x0 + w;
    y1 = y0 + h;
    const others = Object.entries(board.geo ?? {})
      .map(([id, g]) => ({ id, p: project(g[0], g[1]) }))
      .filter(({ id, p: [x, y] }) => !stops.some((s) => s.city === city(id)) && x > x0 && x < x1 && y > y0 && y < y1);
    return { legs, stops, others, frame: [x0, y0, x1, y1] as Box, box: `${x0.toFixed(0)} ${y0.toFixed(0)} ${w.toFixed(0)} ${h.toFixed(0)}`, unit: w / PIXELS };
  }, [board, team]);

  if (!drawn) return null;
  const { unit, frame } = drawn;
  const city = (id: string) => board.geo[id]?.[lang === "ar" ? 3 : 2] ?? id;
  // Each name goes beside its stop (inward first), else on the other side, above or
  // below: the first place inside the frame that covers no stop and no other name.
  const [font, r, gap] = [11 * unit, 10 * unit, 5 * unit];
  const taken: Box[] = drawn.stops.map((s) => [s.x - r, s.y - r, s.x + r, s.y + r]);
  const labels = drawn.stops.map((s) => {
    const name = city(s.id);
    const w = name.length * font * 0.58;
    const side = s.x > (frame[0] + frame[2]) / 2 ? -1 : 1;
    const options = [
      { x: s.x + side * (r + gap), y: s.y + font * 0.35, anchor: side > 0 ? "start" : "end" },
      { x: s.x - side * (r + gap), y: s.y + font * 0.35, anchor: side > 0 ? "end" : "start" },
      { x: s.x, y: s.y - r - gap, anchor: "middle" },
      { x: s.x, y: s.y + r + gap + font * 0.8, anchor: "middle" },
    ] as const;
    const boxOf = (o: (typeof options)[number]): Box => {
      const left = o.anchor === "start" ? o.x : o.anchor === "end" ? o.x - w : o.x - w / 2;
      return [left, o.y - font * 0.8, left + w, o.y + font * 0.2];
    };
    const fits = (b: Box) => b[0] >= frame[0] && b[2] <= frame[2] && b[1] >= frame[1] && b[3] <= frame[3] && taken.every((t) => !overlaps(b, t));
    const best = options.find((o) => fits(boxOf(o))) ?? options[0];
    taken.push(boxOf(best));
    return { ...best, name };
  });
  return (
    <div dir="ltr" className="route-map">
      <svg viewBox={drawn.box} role="img" aria-label={t("routeMap")}>
        {drawn.others.map(({ id, p: [x, y] }) => (
          <circle key={id} cx={x} cy={y} r={2.2 * unit} fill="var(--faint)" opacity="0.5" />
        ))}
        {drawn.legs.map((leg) => (
          <g key={leg.key}>
            {leg.loaded && <path d={leg.d} fill="none" stroke="var(--accent)" strokeWidth={9 * unit} strokeLinecap="round" opacity="0.12" />}
            <path
              className={leg.loaded ? "route-leg" : "route-leg empty"}
              d={leg.d}
              pathLength={1}
              fill="none"
              stroke={leg.loaded ? "var(--accent)" : "var(--warm)"}
              strokeWidth={(leg.loaded ? 2.6 : 1.8) * unit}
              strokeLinecap="round"
              style={{ animationDelay: `${leg.key * 160}ms` }}
            />
          </g>
        ))}
        {drawn.stops.map((s, i) => (
          <g key={s.id}>
            <circle cx={s.x} cy={s.y} r={10 * unit} fill="var(--raised)" stroke="var(--accent)" strokeWidth={1.8 * unit} />
            <text x={s.x} y={s.y + 3.8 * unit} textAnchor="middle" fontSize={10.5 * unit} fontWeight="600" fill="var(--text)">
              {s.n}
            </text>
            <text
              x={labels[i].x}
              y={labels[i].y}
              textAnchor={labels[i].anchor}
              fontSize={font}
              fill="var(--muted)"
              stroke="var(--raised)"
              strokeWidth={3.5 * unit}
              paintOrder="stroke"
              strokeLinejoin="round"
            >
              {labels[i].name}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
