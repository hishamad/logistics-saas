// Every plan run with its results; open one on the board, export it, or compare two.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ChangesAnswer, type PlanRun } from "../api";
import { ChangesView } from "../components/Changes";
import { useI18n, type StringKey } from "../i18n";

const STATUS: Record<PlanRun["status"], StringKey> = {
  queued: "statusQueued",
  running: "statusRunning",
  done: "statusDone",
  failed: "statusFailed",
};

export function History() {
  const { t, lang, number, money, date } = useI18n();
  const [runs, setRuns] = useState<PlanRun[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [comparison, setComparison] = useState<ChangesAnswer | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<PlanRun[]>("/api/plans")
      .then(setRuns)
      .catch((caught: Error) => setError(caught.message));
  }, []);

  function pick(id: string) {
    setComparison(null);
    setPicked((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current.slice(-1), id]));
  }

  async function compare() {
    if (!runs || picked.length !== 2) return;
    // Always from the older plan to the newer one.
    const [newer, older] = [...picked].sort((a, b) => runs.findIndex((r) => r.id === a) - runs.findIndex((r) => r.id === b));
    try {
      setComparison(await api.get<ChangesAnswer>(`/api/plans/${newer}/changes?against=${older}`));
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("historyTitle")}</h1>
          <span className="muted">{t("historyLead")}</span>
        </div>
        <div className="run-controls">
          <span className="muted">{t("compareTwo")}</span>
          <button className="btn btn-primary" onClick={compare} disabled={picked.length !== 2}>
            {t("compareThese")}
          </button>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {comparison?.changes && (
        <section className="panel changes-panel">
          <h2>{t("comparing")}</h2>
          <ChangesView changes={comparison.changes} />
        </section>
      )}
      <section className="panel runs-panel">
        {runs && runs.length === 0 && <p className="empty">{t("noPlans")}</p>}
        {runs && runs.length > 0 && (
          <ul className="runs">
            {runs.map((run, i) => {
              const s = run.summary;
              const done = run.status === "done";
              const figures = s
                ? [
                    { label: t("served"), value: `${number(s.served)} / ${number(s.confirmed)}` },
                    { label: t("colOffers"), value: `${number(s.offers_taken)} / ${number(s.offered)}` },
                    { label: t("emptyShare"), value: s.empty_share != null ? `${Math.round(s.empty_share * 100)}%` : "—" },
                    { label: t("contribution"), value: s.revenue_minor !== null && s.cost_minor !== null ? money(s.revenue_minor - s.cost_minor) : "—" },
                    { label: t("colChanged"), value: s.changed != null ? number(s.changed) : "—" },
                  ]
                : [];
              return (
                <li key={run.id} className={`run-row${picked.includes(run.id) ? " picked" : ""}`}>
                  <input type="checkbox" aria-label={`${t("compareThese")}: ${date(run.created_at)}`} disabled={!done} checked={picked.includes(run.id)} onChange={() => pick(run.id)} />
                  <div className="run-when">
                    <b>
                      {date(run.created_at)}
                      {i === 0 && done && <span className="tag">{t("latestPlan")}</span>}
                    </b>
                    <span className="muted small">
                      {run.created_by ?? "—"} · {number(run.settings.seconds)} {t("secondsShort")}
                    </span>
                  </div>
                  {done && s?.valid !== false ? (
                    <div className="run-figures">
                      {figures.map((f) => (
                        <span key={f.label} className="run-figure">
                          <b>{f.value}</b>
                          <small>{f.label}</small>
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="run-status">
                      <span className={`badge ${run.status === "failed" || done ? "badge-red" : "badge-amber"}`}>{done ? t("findingsLabel") : t(STATUS[run.status])}</span>
                      {run.error && (
                        <span className="muted small" title={run.error}>
                          {run.error}
                        </span>
                      )}
                    </div>
                  )}
                  <div className="row-actions">
                    {done && (
                      <>
                        <Link className="text-btn" to={`/board?run=${run.id}`}>
                          {t("open")} <span className="arrow flip-rtl" aria-hidden="true">→</span>
                        </Link>
                        <a className="text-btn quiet" href={`/api/plans/${run.id}/export.xlsx?lang=${lang}`} download aria-label={t("exportExcel")}>
                          {t("exportShort")} <span className="arrow" aria-hidden="true">↓</span>
                        </a>
                      </>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </>
  );
}
