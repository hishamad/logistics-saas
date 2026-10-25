// The plan board: the plan's numbers on one line, every truck on a timeline, the chosen
// truck beside it, and the orders without a truck below. Dispatchers run plans here.
import { Check, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Board as BoardData, type ChangesAnswer, type Lock as LockRow, type PlanRun, type Steering } from "../api";
import { useAuth } from "../auth";
import { Answer, useWhy } from "../components/Answer";
import { ChangesView } from "../components/Changes";
import { Drawer, type DrawerTarget } from "../components/Drawer";
import { PlanOrbit } from "../components/PlanOrbit";
import { Timeline, useSites } from "../components/Timeline";
import { TruckCard } from "../components/TruckCard";
import { useI18n } from "../i18n";

const DEPTHS = [
  { seconds: 15, label: "depthQuick" },
  { seconds: 30, label: "depthStandard" },
  { seconds: 60, label: "depthThorough" },
] as const;

const busy = (run: PlanRun | null) => run?.status === "queued" || run?.status === "running";

type Operation = { trucks: number; jobs_confirmed: number; jobs_offered: number };

export function Board() {
  const { t, fill, lang, number, money, date } = useI18n();
  const { canPlan } = useAuth();
  const [params, setParams] = useSearchParams();
  const wanted = params.get("run");
  const [runs, setRuns] = useState<PlanRun[] | null>(null);
  const [board, setBoard] = useState<BoardData | null>(null);
  const [boardOf, setBoardOf] = useState<string | null>(null);
  const [seconds, setSeconds] = useState<number>(30);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [drawer, setDrawer] = useState<DrawerTarget | null>(null);
  const [locks, setLocks] = useState<LockRow[]>([]);
  const [changes, setChanges] = useState<ChangesAnswer | null>(null);
  const [operation, setOperation] = useState<Operation | null>(null);

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
  const working = busy(latest);

  // While the engine works, poll the list; the orbit needs the size of the job.
  useEffect(() => {
    if (!working) return;
    api
      .get<Operation>("/api/operation")
      .then(setOperation)
      .catch(() => setOperation(null));
    const poll = setInterval(refresh, 1500);
    return () => clearInterval(poll);
  }, [working, refresh]);

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
      .then((data) => {
        setBoard(data);
        // Start with a truck that has work, in the timeline's own order.
        setSelected((current) => (current && data.teams.some((x) => x.id === current) ? current : (data.teams.find((x) => x.acts.length)?.id ?? null)));
      })
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

  const k = board?.kpis;
  const totalKm = k ? k.loaded_km + k.empty_km : 0;
  const team = board?.teams.find((x) => x.id === selected) ?? null;
  const figures = k
    ? [
        { label: t("kServed"), value: `${number(k.served)} / ${number(k.confirmed)}`, warn: k.served < k.confirmed },
        { label: t("kOffers"), value: `${number(k.accepted)} / ${number(k.offered)}` },
        { label: t("kEmpty"), value: totalKm ? `${number(Math.round((k.empty_km / totalKm) * 100))}%` : "—" },
        { label: t("kContribution"), value: k.revenue !== null && k.cost !== null ? money(k.revenue - k.cost) : "—" },
        { label: t("kPerTruck"), value: k.revenue !== null && k.trucks && k.days ? money(k.revenue / (k.trucks * k.days)) : "—" },
      ]
    : [];

  return (
    <>
      <header className="page-head">
        <div>
          <h1>{t("boardTitle")}</h1>
          {shown && board && (
            <span className="board-meta">
              {t("planFrom")} {date(shown.created_at)} · {fill("depthSeconds", { n: number(shown.settings.seconds) })}
              <span aria-hidden="true">·</span>
              {board.valid ? (
                <span className="check ok">
                  <Check size={14} strokeWidth={2.4} aria-hidden /> {t("passedAll")}
                </span>
              ) : (
                <span className="check bad">
                  <TriangleAlert size={14} aria-hidden /> {t("findingsLabel")}: {board.findings.join(", ")}
                </span>
              )}
            </span>
          )}
        </div>
        <div className="run-controls">
          {board && shown && (
            <a className="text-btn" href={`/api/plans/${shown.id}/export.xlsx?lang=${lang}`} download>
              {t("exportShort")} <span className="arrow" aria-hidden="true">↓</span>
            </a>
          )}
          {canPlan ? (
            <>
              <div className="seg" role="group" aria-label={t("depth")}>
                {DEPTHS.map((d) => (
                  <button key={d.seconds} type="button" aria-pressed={seconds === d.seconds} title={t(d.label)} onClick={() => setSeconds(d.seconds)} disabled={working}>
                    {fill("depthSeconds", { n: number(d.seconds) })}
                  </button>
                ))}
              </div>
              <button className="btn btn-primary" onClick={run} disabled={working || runs === null}>
                {shown ? t("planAgain") : t("runPlan")}
              </button>
            </>
          ) : (
            <span className="muted small">{t("viewerCannotPlan")}</span>
          )}
        </div>
      </header>

      {error && <div className="alert alert-error">{error}</div>}

      {wanted && shown && (
        <p className="older-plan">
          {t("olderPlan")}{" "}
          <Link className="text-btn" to="/board">
            {t("backToLatest")} <span className="arrow flip-rtl" aria-hidden="true">→</span>
          </Link>
        </p>
      )}

      {working && latest && (
        <section className="panel board-running">
          <PlanOrbit
            startedAt={latest.created_at}
            seconds={latest.settings.seconds}
            orders={(operation?.jobs_confirmed ?? 0) + (operation?.jobs_offered ?? 0)}
            trucks={operation?.trucks ?? 0}
          />
        </section>
      )}

      {latest?.status === "failed" && !wanted && (
        <div className="alert alert-error">
          {t("planFailed")} {latest.error}
        </div>
      )}

      {runs !== null && !shown && !working && <p className="empty">{t("noPlanYet")}</p>}

      {board && k && shown && (
        <>
          <section className="kpi-strip" aria-label={t("planNumbers")}>
            {figures.map((f) => (
              <div key={f.label} className="kpi">
                <span className={`kpi-value${f.warn ? " warn" : ""}`}>{f.value}</span>
                <span className="kpi-label">{f.label}</span>
              </div>
            ))}
          </section>

          {board.released.length > 0 && (
            <div className="alert alert-warn">
              {t("releasedLocks")} {board.released.map((id) => board.jobs[id]?.ref ?? id).join(", ")}
            </div>
          )}

          <div className="board-grid">
            <div className="board-main">
              <Timeline board={board} selected={selected} onSelect={setSelected} />
              <Unserved board={board} runId={shown.id} onOpen={setDrawer} />
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
            </div>
            <aside className="board-side">
              {team ? (
                <TruckCard
                  key={team.id}
                  board={board}
                  runId={shown.id}
                  team={team}
                  locks={locks}
                  editable={canPlan}
                  onLocksChanged={loadLocks}
                  onOpen={setDrawer}
                />
              ) : (
                <section className="panel">
                  <p className="empty">{t("clickTruck")}</p>
                </section>
              )}
            </aside>
          </div>
          {drawer && (
            <Drawer
              board={board}
              runId={shown.id}
              target={drawer}
              locks={locks}
              editable={canPlan}
              onLocksChanged={loadLocks}
              onClose={() => setDrawer(null)}
            />
          )}
        </>
      )}
    </>
  );
}

/** Contract orders the plan could not place, each with the plan's own reason on request. */
function Unserved({ board, runId, onOpen }: { board: BoardData; runId: string; onOpen: (target: DrawerTarget) => void }) {
  const { t, count } = useI18n();
  const site = useSites(board);
  const why = useWhy(runId);
  const jobs = board.unserved.filter((id) => board.jobs[id] && !board.jobs[id].offer).map((id) => ({ id, ...board.jobs[id] }));
  return (
    <section className="panel unserved-panel" aria-label={t("unservedTitle")}>
      <div className="panel-head">
        <h2>{t("unservedTitle")}</h2>
        {jobs.length > 0 && <span className="muted small">{count("contractOrders", jobs.length)}</span>}
      </div>
      {jobs.length === 0 ? (
        <p className="all-clear">
          <Check size={16} aria-hidden /> {t("unservedNone")}
        </p>
      ) : (
        <ul className="unserved">
          {jobs.map((job) => (
            <li key={job.id}>
              <div className="unserved-row">
                <button type="button" className="link" onClick={() => onOpen({ kind: "job", id: job.id })}>
                  {job.ref}
                </button>
                <span className="unserved-route">
                  {site(job.from)} → {site(job.to)} · {job.customer} · {job.tonnes} {t("tonnes")}
                </span>
                <button type="button" className="text-btn" onClick={() => void why.ask(job.id)} aria-expanded={why.answer?.job === job.id}>
                  {why.asking === job.id ? t("thinking") : t("whyShort")} <span className="arrow flip-rtl" aria-hidden="true">→</span>
                </button>
              </div>
              {why.answer?.job === job.id && <Answer text={why.answer.text} tone={why.answer.tone} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
