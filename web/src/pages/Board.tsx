// The plan board: run the engine, watch it work, read the result truck by truck.
import { Download, Lock, Play, ShieldAlert, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type Board as BoardData, type ChangesAnswer, type Lock as LockRow, type PlanRun, type Steering } from "../api";
import { ChangesView } from "../components/Changes";
import { useAuth } from "../auth";
import { Drawer, type DrawerTarget } from "../components/Drawer";
import { ACTIVITY_LABEL, Timeline, useSites } from "../components/Timeline";
import { useI18n } from "../i18n";

const DEPTHS = [
  { seconds: 15, label: "depthQuick" },
  { seconds: 30, label: "depthStandard" },
  { seconds: 60, label: "depthThorough" },
] as const;

const busy = (run: PlanRun | null) => run?.status === "queued" || run?.status === "running";

export function Board() {
  const { t, lang, number, money, date } = useI18n();
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const wanted = params.get("run");
  const [runs, setRuns] = useState<PlanRun[] | null>(null);
  const [board, setBoard] = useState<BoardData | null>(null);
  const [boardOf, setBoardOf] = useState<string | null>(null);
  const [seconds, setSeconds] = useState<number>(30);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [, setTick] = useState(0);
  const [drawer, setDrawer] = useState<DrawerTarget | null>(null);
  const [locks, setLocks] = useState<LockRow[]>([]);
  const [changes, setChanges] = useState<ChangesAnswer | null>(null);
  const itinerary = useRef<HTMLElement>(null);

  // Current frozen jobs (they apply to the next plan; the board shows those of its own plan).
  const loadLocks = useCallback(() => {
    api
      .get<Steering>("/api/steering")
      .then((steering) => setLocks(steering.locks))
      .catch(() => setLocks([]));
  }, []);
  useEffect(loadLocks, [loadLocks]);

  const refresh = useCallback(() => {
    api
      .get<PlanRun[]>("/api/plans")
      .then(setRuns)
      .catch((caught: Error) => setError(caught.message));
  }, []);
  useEffect(refresh, [refresh]);

  const latest = runs?.[0] ?? null;
  const shown = runs?.find((run) => (wanted ? run.id === wanted : run.status === "done")) ?? null;

  // While the engine works, poll the list and tick a clock for the progress bar.
  useEffect(() => {
    if (!busy(latest)) return;
    const poll = setInterval(refresh, 1500);
    const tick = setInterval(() => setTick((n) => n + 1), 250);
    return () => {
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [latest, refresh]);

  useEffect(() => {
    if (!shown || shown.status !== "done" || shown.id === boardOf) return;
    setBoardOf(shown.id);
    setChanges(null);
    api
      .get<ChangesAnswer>(`/api/plans/${shown.id}/changes`)
      .then(setChanges)
      .catch(() => setChanges(null));
    api
      .get<BoardData>(`/api/plans/${shown.id}/board`)
      .then(setBoard)
      .catch((caught: Error) => setError(caught.message));
  }, [shown, boardOf]);

  async function run() {
    setError("");
    try {
      await api.post<PlanRun>("/api/plans", { seconds });
      if (wanted) setParams({});
      refresh();
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  function select(teamId: string) {
    setSelected(teamId);
    requestAnimationFrame(() => itinerary.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
  }

  const dispatcher = me?.user.role === "dispatcher";
  const working = busy(latest);
  const k = board?.kpis;
  const totalKm = k ? k.loaded_km + k.empty_km : 0;
  const elapsed = latest ? Math.max(0, (Date.now() - new Date(latest.created_at).getTime()) / 1000) : 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("boardTitle")}</h1>
          {shown && (
            <span className="muted">
              {t("planFrom")} {date(shown.created_at)} · {number(shown.settings.seconds)} {t("secondsShort")}
            </span>
          )}
        </div>
        <div className="run-controls">
          {board && shown && (
            <a className="btn" href={`/api/plans/${shown.id}/export.xlsx?lang=${lang}`} download>
              <Download size={16} aria-hidden /> {t("exportExcel")}
            </a>
          )}
        {dispatcher ? (
          <>
            <select className="input" aria-label={t("depth")} value={seconds} onChange={(e) => setSeconds(Number(e.target.value))} disabled={working}>
              {DEPTHS.map((d) => (
                <option key={d.seconds} value={d.seconds}>
                  {t(d.label)}
                </option>
              ))}
            </select>
            <button className="btn btn-primary" onClick={run} disabled={working || runs === null}>
              <Play size={16} aria-hidden />
              {t("runPlan")}
            </button>
          </>
        ) : (
          <span className="muted">{t("viewerCannotPlan")}</span>
        )}
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {working && latest && (
        <div className="panel progress" role="status">
          <div className="progress-text">
            <b>{t("planning")}</b>
            <span className="muted">
              {number(Math.min(Math.floor(elapsed), latest.settings.seconds))} / {number(latest.settings.seconds)} {t("secondsShort")}
            </span>
          </div>
          <div className="bar">
            <div style={{ width: `${Math.min(100, (elapsed / (latest.settings.seconds + 3)) * 100)}%` }} />
          </div>
        </div>
      )}

      {latest?.status === "failed" && !wanted && (
        <div className="alert alert-error">
          {t("planFailed")} {latest.error}
        </div>
      )}

      {runs !== null && !shown && !working && <p className="empty">{t("noPlanYet")}</p>}

      {board && k && shown && (
        <>
          <section className="tiles board-tiles" aria-label={t("boardTitle")}>
            <Tile label={t("kServed")} value={`${number(k.served)}`} sub={`${t("of")} ${number(k.confirmed)}`} warn={k.served < k.confirmed} />
            <Tile label={t("kOffers")} value={`${number(k.accepted)}`} sub={`${t("of")} ${number(k.offered)}`} />
            <Tile
              label={t("kEmpty")}
              value={totalKm ? `${number(Math.round((k.empty_km / totalKm) * 100))}%` : "—"}
              sub={`${number(k.empty_km)} ${t("colKm")}`}
            />
            <Tile label={t("kPerTruck")} value={k.revenue !== null && k.trucks && k.days ? money(k.revenue / (k.trucks * k.days)) : "—"} />
            <Tile label={t("kContribution")} value={k.revenue !== null && k.cost !== null ? money(k.revenue - k.cost) : "—"} sub={`${t("kCost")} ${money(k.cost)}`} />
          </section>

          <div className={`check ${board.valid ? "ok" : "bad"}`}>
            {board.valid ? <ShieldCheck size={16} aria-hidden /> : <ShieldAlert size={16} aria-hidden />}
            {board.valid ? t("passed") : `${t("findingsLabel")}: ${board.findings.join(", ")}`}
          </div>

          {board.released.length > 0 && (
            <div className="alert alert-warn">
              {t("releasedLocks")} {board.released.map((id) => board.jobs[id]?.ref ?? id).join(", ")}
            </div>
          )}

          {changes?.changes && changes.against && (
            <section className="panel changes-panel">
              <h2>
                {t("changesTitle")}{" "}
                <span className="muted small">
                  {t("changesSince")} {date(changes.against.created_at)}
                </span>
              </h2>
              <ChangesView changes={changes.changes} />
            </section>
          )}

          <Timeline board={board} selected={selected} onSelect={select} />

          <div className="board-bottom">
            <section className="panel" ref={itinerary} aria-label={t("itinerary")}>
              <Itinerary
                board={board}
                teamId={selected}
                locks={locks}
                onClose={() => setSelected(null)}
                onOpen={setDrawer}
              />
            </section>
            <Unserved board={board} onOpen={setDrawer} />
          </div>
          {drawer && (
            <Drawer
              board={board}
              runId={shown.id}
              target={drawer}
              locks={locks}
              editable={dispatcher}
              onLocksChanged={loadLocks}
              onClose={() => setDrawer(null)}
            />
          )}
        </>
      )}
    </>
  );
}

function Tile({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className={`value${warn ? " warn" : ""}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function Itinerary({
  board,
  teamId,
  locks,
  onClose,
  onOpen,
}: {
  board: BoardData;
  teamId: string | null;
  locks: LockRow[];
  onClose: () => void;
  onOpen: (target: DrawerTarget) => void;
}) {
  const { t, number, money, date } = useI18n();
  const site = useSites(board);
  const team = board.teams.find((candidate) => candidate.id === teamId);
  if (!team) {
    return (
      <>
        <h2>{t("itinerary")}</h2>
        <p className="empty">{t("clickTruck")}</p>
      </>
    );
  }
  const origin = new Date(board.origin).getTime();
  const when = (minute: number) =>
    date(new Date(origin + minute * 60000).toISOString(), {
      dateStyle: undefined,
      timeStyle: undefined,
      weekday: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
  const s = team.stats;
  return (
    <>
      <div className="itinerary-head">
        <div>
          <h2>
            {team.name} · {site(team.depot)}
          </h2>
          <p className="muted">
            {number(s.jobs)} {t("jobsCount")} · {money(s.revenue)} · {number(s.driving_h)} {t("drivingHours")} · {number(s.loaded_km)} {t("kmLoaded")} ·{" "}
            {number(s.empty_km)} {t("kmEmpty")}
          </p>
        </div>
        <div className="result-actions">
          <button className="btn" onClick={() => onOpen({ kind: "truck", id: team.id })}>
            {t("whatIf")}
          </button>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("close")}
          </button>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("colStart")}</th>
              <th>{t("colEnd")}</th>
              <th>{t("colActivity")}</th>
              <th>{t("colWhere")}</th>
              <th className="num">{t("colKm")}</th>
              <th>{t("colJob")}</th>
            </tr>
          </thead>
          <tbody>
            {team.acts.map((act, i) => {
              const job = act[3] ? board.jobs[act[3]] : null;
              return (
                <tr key={i}>
                  <td>{when(act[1])}</td>
                  <td>{when(act[2])}</td>
                  <td>
                    <span className={`dot k-${["loaded", "empty", "handling", "waiting", "rest"][act[0]]}`} />
                    {t(ACTIVITY_LABEL[act[8]])}
                    {act[7].length > 0 && <span className="muted"> ({act[7].length})</span>}
                  </td>
                  <td>{act[4] === act[5] ? site(act[4]) : `${site(act[4])} → ${site(act[5])}`}</td>
                  <td className="num">{act[6] ? number(act[6]) : ""}</td>
                  <td>
                    {job ? (
                      <>
                        <button className="link" onClick={() => onOpen({ kind: "job", id: act[3]! })}>
                          {job.ref}
                        </button>{" "}
                        {locks.some((l) => l.job_id === act[3]) && <Lock size={12} aria-label={t("frozenBadge")} />}{" "}
                        <span className="muted">{job.customer}</span>
                        {job.offer && <span className="badge badge-amber small">{t("spot")}</span>}
                      </>
                    ) : (
                      ""
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Unserved({ board, onOpen }: { board: BoardData; onOpen: (target: DrawerTarget) => void }) {
  const { t, number } = useI18n();
  const site = useSites(board);
  const jobs = board.unserved.filter((id) => board.jobs[id] && !board.jobs[id].offer).map((id) => ({ id, ...board.jobs[id] }));
  return (
    <section className="panel" aria-label={t("unservedTitle")}>
      <h2>
        {t("unservedTitle")} {jobs.length > 0 && <span className="badge badge-red">{number(jobs.length)}</span>}
      </h2>
      {jobs.length === 0 ? (
        <p className="empty">{t("unservedNone")}</p>
      ) : (
        <ul className="unserved">
          {jobs.map((job) => (
            <li key={job.ref}>
              <button className="link" onClick={() => onOpen({ kind: "job", id: job.id })}>
                <b>{job.ref}</b>
              </button>{" "}
              <span className="muted">{job.customer}</span>
              <div>
                {site(job.from)} → {site(job.to)} · {job.tonnes} {t("tonnes")}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
