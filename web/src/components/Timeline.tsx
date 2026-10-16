// The truck timeline: one row per truck, its activities as coloured bars over time.
// Positions use inline-start, so in Arabic time runs right-to-left.
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import type { Board, BoardActivity, BoardTeam } from "../api";
import { useI18n, type StringKey } from "../i18n";

const LABEL_WIDTH = 210;
const RIYADH_OFFSET = 180; // minutes; Saudi Arabia has no daylight saving
// Intl rejects dateStyle/timeStyle mixed with weekday/hour, so clear the defaults.
const PLAIN = { dateStyle: undefined, timeStyle: undefined } as const;
const KIND_CLASS = ["k-loaded", "k-empty", "k-handling", "k-waiting", "k-rest"];
export const ACTIVITY_LABEL: Record<BoardActivity[8], StringKey> = {
  loaded: "actLoaded",
  empty: "actEmpty",
  loading: "actLoading",
  unloading: "actUnloading",
  turnaround: "actTurnaround",
  waiting: "actWaiting",
  rest: "actRest",
};

type Sort = "depot" | "empty" | "revenue" | "idle";

export function useSites(board: Board) {
  const { lang } = useI18n();
  return (id: string) => {
    const names = board.sites[id];
    if (!names) return id;
    return lang === "ar" && names[1] ? names[1] : names[0];
  };
}

export function Timeline({
  board,
  selected,
  onSelect,
}: {
  board: Board;
  selected: string | null;
  onSelect: (teamId: string) => void;
}) {
  const { t, lang, number, date } = useI18n();
  const site = useSites(board);
  const origin = useMemo(() => new Date(board.origin).getTime(), [board.origin]);
  const at = (minute: number) => new Date(origin + minute * 60000).toISOString();
  const clock = (minute: number) => date(at(minute), { ...PLAIN, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

  const [search, setSearch] = useState("");
  const [depot, setDepot] = useState("");
  const [sort, setSort] = useState<Sort>("depot");
  const [zoom, setZoom] = useState<"week" | "detail">("week");
  const [hover, setHover] = useState<{ x: number; y: number; team: BoardTeam; act: BoardActivity; minute: number } | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);

  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const start = 0;
  const end = Math.ceil(board.end / 1440) * 1440;
  const laneWidth = zoom === "week" ? Math.max(560, width - LABEL_WIDTH - 2) : ((end - start) / 60) * 22;
  const px = laneWidth / (end - start);
  const x = (minute: number) => (minute - start) * px;

  const frozen = useMemo(() => new Set(board.frozen), [board.frozen]);
  const depots = useMemo(() => [...new Set(board.teams.map((team) => team.depot))], [board.teams]);
  const teams = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const matches = (team: BoardTeam) => {
      if (depot && team.depot !== depot) return false;
      if (!needle) return true;
      const hay = [team.name, team.id, ...(board.sites[team.depot] ?? [])];
      for (const act of team.acts) {
        hay.push(...(board.sites[act[4]] ?? []), ...(board.sites[act[5]] ?? []));
        if (act[3]) hay.push(board.jobs[act[3]].ref, board.jobs[act[3]].customer);
      }
      return hay.some((value) => value.toLowerCase().includes(needle));
    };
    const order: Record<Sort, (a: BoardTeam, b: BoardTeam) => number> = {
      depot: (a, b) => depots.indexOf(a.depot) - depots.indexOf(b.depot) || a.name.localeCompare(b.name, "en", { numeric: true }),
      empty: (a, b) => b.stats.empty_km - a.stats.empty_km,
      revenue: (a, b) => b.stats.revenue - a.stats.revenue,
      idle: (a, b) => a.stats.jobs - b.stats.jobs,
    };
    return board.teams.filter(matches).sort(order[sort]);
  }, [board, search, depot, sort, depots]);

  // Riyadh midnights within the window, and the night bands (18:00-06:00) around them.
  const midnights = useMemo(() => {
    const first = start - ((((origin / 60000 + RIYADH_OFFSET + start) % 1440) + 1440) % 1440);
    const result: number[] = [];
    for (let m = first; m <= end + 1440; m += 1440) result.push(m);
    return result;
  }, [origin, end]);
  const background = (
    <>
      {midnights.map((m) => {
        const a = Math.max(start, m - 360);
        const b = Math.min(end, m + 360);
        return b > a ? <div key={`n${m}`} className="tl-night" style={{ insetInlineStart: x(a), width: x(b) - x(a) }} /> : null;
      })}
      {midnights.filter((m) => m > start && m < end).map((m) => (
        <div key={`d${m}`} className="tl-dayline" style={{ insetInlineStart: x(m) }} />
      ))}
      <div className="tl-horizon" style={{ insetInlineStart: x(board.horizonEnd) }} />
    </>
  );
  const stepHours = [3, 6, 12, 24].find((h) => px * 60 * h >= 52) ?? 24;
  // Narrow days get a shorter date so the labels never overlap.
  const dayWidth = px * 1440;
  const dayLabel: Intl.DateTimeFormatOptions =
    dayWidth >= 130
      ? { ...PLAIN, weekday: "short", day: "numeric", month: "short" }
      : dayWidth >= 75
        ? { ...PLAIN, weekday: "short", day: "numeric" }
        : { ...PLAIN, day: "numeric", month: "numeric" };
  const ticks: { m: number; day: boolean }[] = [];
  for (let m = midnights[0]; m < end; m += stepHours * 60) if (m >= start) ticks.push({ m, day: (m - midnights[0]) % 1440 === 0 });

  function locate(event: MouseEvent<HTMLDivElement>, team: BoardTeam) {
    const rect = event.currentTarget.getBoundingClientRect();
    const offset = lang === "ar" ? rect.right - event.clientX : event.clientX - rect.left;
    const minute = offset / px + start;
    const slack = 4 / px;
    let best: BoardActivity | null = null;
    let distance = Infinity;
    for (const act of team.acts) {
      const d = minute < act[1] ? act[1] - minute : minute > act[2] ? minute - act[2] : 0;
      if (d < distance && d <= slack) {
        best = act;
        distance = d;
      }
    }
    setHover(best ? { x: event.clientX, y: event.clientY, team, act: best, minute } : null);
  }

  let group: string | null = null;
  return (
    <section className="panel tl" aria-label={t("boardTitle")}>
      <div className="tl-controls">
        <input className="input tl-search" type="search" placeholder={t("search")} aria-label={t("search")} value={search} onChange={(e) => setSearch(e.target.value)} />
        <select className="input" aria-label={t("allDepots")} value={depot} onChange={(e) => setDepot(e.target.value)}>
          <option value="">{t("allDepots")}</option>
          {depots.map((d) => (
            <option key={d} value={d}>
              {site(d)}
            </option>
          ))}
        </select>
        <select className="input" aria-label={t("sortDepot")} value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
          <option value="depot">{t("sortDepot")}</option>
          <option value="empty">{t("sortEmpty")}</option>
          <option value="revenue">{t("sortRevenue")}</option>
          <option value="idle">{t("sortIdle")}</option>
        </select>
        <div className="segmented" role="group">
          <button type="button" aria-pressed={zoom === "week"} onClick={() => setZoom("week")}>
            {t("week")}
          </button>
          <button type="button" aria-pressed={zoom === "detail"} onClick={() => setZoom("detail")}>
            {t("detail")}
          </button>
        </div>
      </div>
      <div className="tl-legend">
        <span><i className="key k-loaded" />{t("legendLoaded")}</span>
        <span><i className="key k-loaded offer" />{t("legendOffer")}</span>
        <span><i className="key k-empty" />{t("legendEmpty")}</span>
        <span><i className="key k-handling" />{t("legendHandling")}</span>
        <span><i className="key k-waiting" />{t("legendWaiting")}</span>
        <span><i className="key k-rest" />{t("legendRest")}</span>
        {board.frozen.length > 0 && <span><i className="key k-loaded frozen" />{t("legendFrozen")}</span>}
        <span className="tl-note">{t("nightNote")}</span>
      </div>
      <div className="tl-scroll" ref={scroller}>
        <div className="tl-axis">
          <div className="tl-corner">
            {number(teams.length)} / {number(board.teams.length)} {t("trucksShown")}
          </div>
          <div className="tl-ticks" style={{ width: laneWidth }}>
            {ticks.map(({ m, day }) => (
              <div key={m} className={`tl-tick${day ? " day" : ""}`} style={{ insetInlineStart: x(m) }}>
                {day ? date(at(m), dayLabel) : ""}
                {stepHours < 24 && <span className="hour">{date(at(m), { ...PLAIN, hour: "2-digit", minute: "2-digit", hourCycle: "h23" })}</span>}
              </div>
            ))}
          </div>
        </div>
        {teams.length === 0 && <p className="empty">{t("noMatches")}</p>}
        {teams.map((team) => {
          const heading = sort === "depot" && team.depot !== group ? (group = team.depot) : null;
          return (
            <div key={team.id}>
              {heading && <div className="tl-group">{site(heading)}</div>}
              <div className={`tl-row${selected === team.id ? " selected" : ""}`} onClick={() => onSelect(team.id)}>
                <div className="tl-who">
                  <b>{team.name}</b>
                  <span>
                    {team.equipment.replace("_", " ")} · {number(team.stats.jobs)} {t("jobsCount")}
                  </span>
                </div>
                <div className="tl-lane" style={{ width: laneWidth }} onMouseMove={(e) => locate(e, team)} onMouseLeave={() => setHover(null)}>
                  {background}
                  {team.acts.map((act, i) => {
                    const offer = act[0] === 0 && act[3] && board.jobs[act[3]].offer;
                    const left = x(act[1]);
                    const w = Math.max(1.5, x(act[2]) - left - (x(act[2]) - left > 3 ? 1 : 0));
                    return (
                      <div key={i} className={`tl-seg ${KIND_CLASS[act[0]]}${offer ? " offer" : ""}${act[3] && frozen.has(act[3]) ? " frozen" : ""}`} style={{ insetInlineStart: left, width: w }}>
                        {act[7].map((p, j) => (
                          <i key={j} className="tl-pause" style={{ insetInlineStart: x(p[1]) - left, width: Math.max(1, x(p[2]) - x(p[1])) }} />
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {hover && (
        <div className="tl-tip" style={{ left: Math.min(hover.x + 14, window.innerWidth - 330), top: Math.min(hover.y + 14, window.innerHeight - 180) }} role="tooltip">
          <Tip board={board} act={hover.act} minute={hover.minute} clock={clock} />
        </div>
      )}
    </section>
  );
}

function Tip({ board, act, minute, clock }: { board: Board; act: BoardActivity; minute: number; clock: (m: number) => string }) {
  const { t, number, money, span } = useI18n();
  const site = useSites(board);
  const job = act[3] ? board.jobs[act[3]] : null;
  const pause = act[7].find((p) => minute >= p[1] && minute <= p[2]);
  const duration = act[2] - act[1];
  const breaks = act[7].filter((p) => p[0] === "break").length;
  const rests = act[7].length - breaks;
  return (
    <>
      <b>
        {t(ACTIVITY_LABEL[act[8]])}
        {job ? ` · ${job.ref}` : ""}
        {job?.offer ? ` (${t("spot")})` : ""}
      </b>
      <div>{act[4] === act[5] ? site(act[4]) : `${site(act[4])} → ${site(act[5])}`}</div>
      <div className="muted">
        {clock(act[1])} → {clock(act[2])} · {span(duration)}
        {act[6] ? ` · ${number(act[6])} ${t("colKm")}` : ""}
      </div>
      {act[7].length > 0 && (
        <div className="muted">
          {breaks > 0 && `${breaks} ${t("breaks")}`} {rests > 0 && `${rests} ${t("rests")}`}
          {pause ? ` (${pause[0] === "rest" ? t("actRest") : t("breaks")}: ${clock(pause[2])})` : ""}
        </div>
      )}
      {job && (
        <div className="muted">
          {job.customer} · {job.tonnes} {t("tonnes")} · {money(job.revenue)}
        </div>
      )}
    </>
  );
}
