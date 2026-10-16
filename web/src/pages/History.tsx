// Every plan run with its results; open one on the board, export it, or compare two.
import { Download, GitCompare } from "lucide-react";
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
            <GitCompare size={16} aria-hidden /> {t("compareThese")}
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
      <section className="panel">
        {runs && runs.length === 0 && <p className="empty">{t("noPlans")}</p>}
        {runs && runs.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th />
                  <th>{t("created")}</th>
                  <th>{t("colBy")}</th>
                  <th>{t("status")}</th>
                  <th className="num">{t("colDepth")}</th>
                  <th className="num">{t("served")}</th>
                  <th className="num">{t("colOffers")}</th>
                  <th className="num">{t("emptyShare")}</th>
                  <th className="num">{t("contribution")}</th>
                  <th className="num">{t("colChanged")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => {
                  const s = run.summary;
                  const done = run.status === "done";
                  return (
                    <tr key={run.id} className={picked.includes(run.id) ? "picked" : undefined}>
                      <td>
                        <input type="checkbox" aria-label={t("compareThese")} disabled={!done} checked={picked.includes(run.id)} onChange={() => pick(run.id)} />
                      </td>
                      <td>{date(run.created_at)}</td>
                      <td>{run.created_by ?? "—"}</td>
                      <td>
                        <span className={`badge ${run.status === "failed" ? "badge-red" : done ? (s?.valid ? "" : "badge-red") : "badge-amber"}`}>
                          {t(STATUS[run.status])}
                        </span>
                        {run.status === "failed" && run.error && (
                          <div className="muted small wrap" title={run.error}>
                            {run.error}
                          </div>
                        )}
                      </td>
                      <td className="num">
                        {number(run.settings.seconds)} {t("secondsShort")}
                      </td>
                      <td className="num">{s ? `${number(s.served)} / ${number(s.confirmed)}` : "—"}</td>
                      <td className="num">{s ? `${number(s.offers_taken)} / ${number(s.offered)}` : "—"}</td>
                      <td className="num">{s?.empty_share != null ? `${Math.round(s.empty_share * 100)}%` : "—"}</td>
                      <td className="num">{s && s.revenue_minor !== null && s.cost_minor !== null ? money(s.revenue_minor - s.cost_minor) : "—"}</td>
                      <td className="num">{s?.changed != null ? number(s.changed) : "—"}</td>
                      <td>
                        {done && (
                          <span className="row-actions">
                            <Link to={`/board?run=${run.id}`}>{t("open")}</Link>
                            <a href={`/api/plans/${run.id}/export.xlsx?lang=${lang}`} download aria-label={t("exportExcel")}>
                              <Download size={15} aria-hidden />
                            </a>
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
