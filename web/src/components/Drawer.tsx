// Side drawer on the plan board: explain a job, freeze it, or ask "what if?"
// about a job or a truck. What-ifs re-plan in the background and are polled.
import { HelpCircle, Lock, Unlock, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Board, type Lock as LockRow, type WhatIfChange, type WhatIfNumbers, type WhatIfRun, type WhyAnswer } from "../api";
import { useI18n, type StringKey } from "../i18n";
import { addHours, fromRiyadhInput, toRiyadhInput } from "../time";
import { useSites } from "./Timeline";

export type DrawerTarget = { kind: "job"; id: string } | { kind: "truck"; id: string };

export function Drawer({
  board,
  runId,
  target,
  locks,
  editable,
  onLocksChanged,
  onClose,
}: {
  board: Board;
  runId: string;
  target: DrawerTarget;
  locks: LockRow[];
  editable: boolean;
  onLocksChanged: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  useEffect(() => {
    const close = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true">
        <button className="btn btn-ghost drawer-close" onClick={onClose} aria-label={t("close")}>
          <X size={18} aria-hidden />
        </button>
        {target.kind === "job" ? (
          <JobPanel key={target.id} board={board} runId={runId} jobId={target.id} locks={locks} editable={editable} onLocksChanged={onLocksChanged} />
        ) : (
          <TruckPanel key={target.id} board={board} runId={runId} teamId={target.id} editable={editable} />
        )}
      </aside>
    </>
  );
}

function JobPanel({
  board,
  runId,
  jobId,
  locks,
  editable,
  onLocksChanged,
}: {
  board: Board;
  runId: string;
  jobId: string;
  locks: LockRow[];
  editable: boolean;
  onLocksChanged: () => void;
}) {
  const { t, lang, money } = useI18n();
  const site = useSites(board);
  const job = board.jobs[jobId];
  const team = board.teams.find((x) => x.acts.some((act) => act[3] === jobId));
  const lock = locks.find((l) => l.job_id === jobId);
  const [answer, setAnswer] = useState<WhyAnswer | null>(null);
  const [error, setError] = useState("");
  const [moveTo, setMoveTo] = useState("");

  useEffect(() => {
    setAnswer(null);
    api
      .get<WhyAnswer>(`/api/plans/${runId}/why/${jobId}?lang=${lang}`)
      .then(setAnswer)
      .catch((caught: Error) => setError(caught.message));
  }, [runId, jobId, lang]);

  async function toggleLock() {
    setError("");
    try {
      if (lock) await api.del(`/api/locks/${jobId}`);
      else if (team) await api.post("/api/locks", { job_id: jobId, team_id: team.id });
      onLocksChanged();
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  const others = board.teams.filter((x) => x.id !== team?.id && x.equipment === job.equipment).sort((a, b) => a.name.localeCompare(b.name, "en", { numeric: true }));
  return (
    <>
      <h2>
        {job.ref} {job.offer && <span className="badge badge-amber">{t("spot")}</span>}
        {lock && (
          <span className="badge">
            <Lock size={12} aria-hidden /> {t("frozenBadge")}
          </span>
        )}
      </h2>
      <p className="muted">
        {job.customer} · {site(job.from)} → {site(job.to)} · {job.tonnes} {t("tonnes")} · {money(job.revenue)}
      </p>
      <p>
        {team ? (
          <>
            {t("onTruck")}: <b>{team.name}</b>
          </>
        ) : (
          <span className="badge badge-red">{t("notPlanned")}</span>
        )}
        {answer?.facts.assigned && <span className="muted"> · {answer.facts.assigned.pickup_riyadh}</span>}
      </p>
      {error && <div className="alert alert-error">{error}</div>}
      {editable && team && (
        <button className="btn" onClick={toggleLock}>
          {lock ? <Unlock size={16} aria-hidden /> : <Lock size={16} aria-hidden />} {lock ? t("unfreeze") : job.offer ? t("freezeAccepts") : t("freezeOnTruck")}
        </button>
      )}
      {editable && <p className="muted small">{t("nextPlanNote")}</p>}

      <h3>
        <HelpCircle size={16} aria-hidden /> {team ? t("why") : t("whyUnserved")}
      </h3>
      {!answer ? <p className="muted">{t("whyLoading")}</p> : <Why answer={answer} />}

      {editable && (
        <>
          <h3>{t("whatIf")}</h3>
          <WhatIf runId={runId} change={{ kind: "drop", job: jobId }} label={t("wiCancel")} />
          <WhatIf
            runId={runId}
            change={moveTo ? { kind: "assign", job: jobId, team: moveTo } : null}
            label={t("wiMove")}
            input={
              <select className="input" value={moveTo} onChange={(e) => setMoveTo(e.target.value)}>
                <option value="">—</option>
                {others.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </select>
            }
          />
        </>
      )}
    </>
  );
}

function Why({ answer }: { answer: WhyAnswer }) {
  const { t, number, money } = useI18n();
  const f = answer.facts;
  const reasons = Object.entries(f.trucks_that_cannot_take_it);
  return (
    <div className="why">
      <p dir="auto">{answer.text}</p>
      {f.alternatives.length > 0 && (
        <table className="compact">
          <thead>
            <tr>
              <th>{t("alternatives")}</th>
              <th className="num">{t("extraCost")}</th>
              {f.assigned && <th className="num">{t("moreThanChosen")}</th>}
            </tr>
          </thead>
          <tbody>
            {f.alternatives.map((a) => (
              <tr key={a.truck}>
                <td>{a.truck}</td>
                <td className="num">{money(a.extra_cost_sar * 100)}</td>
                {f.assigned && <td className="num">+{money((a.more_than_chosen_sar ?? 0) * 100)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {reasons.length > 0 && (
        <>
          <div className="muted small">{t("cannotTake")}</div>
          <ul className="reasons">
            {reasons.map(([reason, count]) => (
              <li key={reason}>
                <b>{number(count)}</b> {t(`reason_${reason}` as StringKey) ?? reason}
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="muted small">
        {t("explainedBy")}: {answer.source === "template" ? t("templateSource") : answer.source}
      </div>
    </div>
  );
}

function TruckPanel({ board, runId, teamId, editable }: { board: Board; runId: string; teamId: string; editable: boolean }) {
  const { t, number, money } = useI18n();
  const site = useSites(board);
  const team = board.teams.find((x) => x.id === teamId)!;
  const [from, setFrom] = useState(toRiyadhInput(board.origin));
  const [until, setUntil] = useState(toRiyadhInput(addHours(board.origin, 24)));
  const valid = from && until && until > from;
  return (
    <>
      <h2>{team.name}</h2>
      <p className="muted">
        {site(team.depot)} · {number(team.stats.jobs)} {t("jobsCount")} · {money(team.stats.revenue)}
      </p>
      {editable ? (
        <>
          <h3>{t("wiUnavailable")}</h3>
          <div className="form-grid">
            <label className="field">
              <span>{t("fieldFrom")}</span>
              <input className="input" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label className="field">
              <span>{t("fieldUntil")}</span>
              <input className="input" type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
            </label>
          </div>
          <WhatIf
            runId={runId}
            change={valid ? { kind: "unavailable", team: teamId, start: fromRiyadhInput(from), end: fromRiyadhInput(until) } : null}
            label=""
          />
        </>
      ) : (
        <p className="muted">{t("viewerSteer")}</p>
      )}
    </>
  );
}

function WhatIf({ runId, change, label, input }: { runId: string; change: WhatIfChange | null; label: string; input?: ReactNode }) {
  const { t } = useI18n();
  const [run, setRun] = useState<WhatIfRun | null>(null);
  const [error, setError] = useState("");
  const working = run?.status === "queued" || run?.status === "running";

  useEffect(() => {
    if (!run || !working) return;
    const poll = setInterval(() => {
      api
        .get<WhatIfRun>(`/api/whatif/${run.id}`)
        .then(setRun)
        .catch((caught: Error) => setError(caught.message));
    }, 1500);
    return () => clearInterval(poll);
  }, [run, working]);

  async function start() {
    if (!change) return;
    setError("");
    try {
      setRun(await api.post<WhatIfRun>(`/api/plans/${runId}/whatif`, change));
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  return (
    <div className="whatif">
      <div className="whatif-ask">
        {label && <span>{label}</span>}
        {input}
        <button className="btn" onClick={start} disabled={!change || working}>
          {t("wiRun")}
        </button>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {working && (
        <p className="muted">
          <span className="spinner" aria-hidden /> {t("wiWorking")}
        </p>
      )}
      {run?.status === "failed" && <div className="alert alert-error">{t("wiFailed")}</div>}
      {run?.status === "done" && run.result && <WhatIfAnswer result={run.result} />}
    </div>
  );
}

function WhatIfAnswer({ result }: { result: NonNullable<WhatIfRun["result"]> }) {
  const { t, lang, number, money } = useI18n();
  const f = result.facts;
  const rows: { key: keyof WhatIfNumbers; label: StringKey; money?: boolean }[] = [
    { key: "contract_jobs_served", label: "mContract" },
    { key: "offers_taken", label: "mOffers" },
    { key: "contribution_sar", label: "mContribution", money: true },
    { key: "empty_km", label: "mEmpty" },
  ];
  const show = (value: number | null | undefined, isMoney?: boolean) =>
    value == null ? "—" : isMoney ? money(value * 100) : number(value);
  const signed = (value: number | null | undefined, isMoney?: boolean) =>
    value == null ? "—" : `${value > 0 ? "+" : value < 0 ? "−" : ""}${show(Math.abs(value), isMoney)}`;
  return (
    <div className="whatif-answer">
      <p dir="auto">{result.text[lang]}</p>
      <table className="compact">
        <thead>
          <tr>
            <th />
            <th className="num">{t("wiBefore")}</th>
            <th className="num">{t("wiAfter")}</th>
            <th className="num">{t("wiDiff")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>{t(row.label)}</td>
              <td className="num">{show(f.before[row.key], row.money)}</td>
              <td className="num">{show(f.after[row.key], row.money)}</td>
              <td className="num">
                <b>{signed(f.difference[row.key], row.money)}</b>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        {number(f.jobs_moved_count)} {t("wiMoved")} · {number(f.trucks_whose_plan_changes)} {t("wiTrucks")}
      </p>
      {f.jobs_no_longer_served.length > 0 && (
        <p className="small">
          {t("wiLost")} {f.jobs_no_longer_served.join(", ")}
        </p>
      )}
      {f.jobs_newly_served.length > 0 && (
        <p className="small">
          {t("wiGained")} {f.jobs_newly_served.join(", ")}
        </p>
      )}
      <p className="muted small">{t("wiNoise")}</p>
    </div>
  );
}
