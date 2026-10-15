import { useEffect, useState } from "react";
import { api, type Operation, type PlanRun } from "../api";
import { useI18n, type StringKey } from "../i18n";

const STATUS: Record<PlanRun["status"], StringKey> = {
  queued: "statusQueued",
  running: "statusRunning",
  done: "statusDone",
  failed: "statusFailed",
};

export function Overview() {
  const { t, number, money, date } = useI18n();
  const [operation, setOperation] = useState<Operation | null>(null);
  const [plans, setPlans] = useState<PlanRun[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.get<Operation>("/api/operation"), api.get<PlanRun[]>("/api/plans")])
      .then(([op, runs]) => {
        setOperation(op);
        setPlans(runs);
      })
      .catch((caught: Error) => setError(caught.message));
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("overviewTitle")}</h1>
          {operation && <span className="muted">{operation.name}</span>}
        </div>
        <span className="badge badge-amber">{t("syntheticNote")}</span>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {operation && (
        <section className="tiles" aria-label={t("overviewTitle")}>
          <Tile label={t("trucks")} value={number(operation.trucks)} />
          <Tile label={t("contractJobs")} value={number(operation.jobs_confirmed)} />
          <Tile label={t("offers")} value={number(operation.jobs_offered)} />
          <Tile label={t("sites")} value={number(operation.sites)} />
          <Tile
            label={t("horizon")}
            value={`${date(operation.horizon.start, { timeStyle: undefined, dateStyle: "short" })} – ${date(operation.horizon.end, { timeStyle: undefined, dateStyle: "short" })}`}
            small
          />
          <Tile label={t("drivingRules")} value={operation.driving_rules ? t("on") : t("off")} small />
        </section>
      )}
      <section className="panel">
        <h2>{t("recentPlans")}</h2>
        {plans.length === 0 ? (
          <p className="empty">{t("noPlans")}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("created")}</th>
                  <th>{t("status")}</th>
                  <th className="num">{t("served")}</th>
                  <th className="num">{t("emptyShare")}</th>
                  <th className="num">{t("contribution")}</th>
                  <th>{t("valid")}</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((run) => {
                  const s = run.summary;
                  return (
                    <tr key={run.id}>
                      <td>{date(run.created_at)}</td>
                      <td>
                        <span className={`badge ${run.status === "failed" ? "badge-red" : run.status === "done" ? "" : "badge-amber"}`}>
                          {t(STATUS[run.status])}
                        </span>
                      </td>
                      <td className="num">{s ? `${number(s.served)} / ${number(s.confirmed)}` : "—"}</td>
                      <td className="num">{s?.empty_share != null ? `${Math.round(s.empty_share * 100)}%` : "—"}</td>
                      <td className="num">
                        {s && s.revenue_minor !== null && s.cost_minor !== null ? money(s.revenue_minor - s.cost_minor) : "—"}
                      </td>
                      <td>{s ? (s.valid ? "✓" : "✗") : "—"}</td>
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

function Tile({ label, value, small }: { label: string; value: string; small?: boolean }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value" style={small ? { fontSize: 17, marginTop: 6 } : undefined}>
        {value}
      </div>
    </div>
  );
}
