// The morning view: what needs the dispatcher's attention, then the latest plan.
import { AlertTriangle, CheckCircle2, Info, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Attention, type OverviewData } from "../api";
import { useAuth } from "../auth";
import { useI18n, type StringKey } from "../i18n";

// What each item links to, and how serious it is.
const ACTIONS: Record<Attention["kind"], { to: string; label: StringKey; level: "warn" | "info" }> = {
  no_plan: { to: "/board", label: "goRunPlan", level: "warn" },
  plan_out_of_date: { to: "/board", label: "goRunPlan", level: "warn" },
  plan_invalid: { to: "/board", label: "goBoard", level: "warn" },
  unserved: { to: "/board", label: "goBoard", level: "warn" },
  expired: { to: "/data", label: "goData", level: "warn" },
  released: { to: "/rules", label: "goRules", level: "warn" },
  window_behind: { to: "/data", label: "goNextDay", level: "info" },
  notify: { to: "/board", label: "goExport", level: "info" },
  idle_trucks: { to: "/board", label: "goBoard", level: "info" },
};

export function Overview() {
  const { t, number, money, date } = useI18n();
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .get<OverviewData>("/api/overview")
        .then((d) => alive && setData(d))
        .catch((caught: Error) => alive && setError(caught.message));
    load();
    const every = setInterval(load, 15000); // keep the morning view current
    return () => {
      alive = false;
      clearInterval(every);
    };
  }, []);

  const op = data?.operation;
  const s = data?.latest?.summary;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("overviewTitle")}</h1>
          {op && (
            <span className="muted">
              {op.name} · {date(op.window.start)} – {date(op.window.end)}
            </span>
          )}
        </div>
        <span className="badge badge-amber">{t("syntheticNote")}</span>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {data?.running && (
        <div className="alert alert-info">
          <Loader2 size={15} className="spin" aria-hidden /> {t("planRunning")}
        </div>
      )}
      {data && (
        <section className="panel attention" aria-label={t("attentionTitle")}>
          <h2>{t("attentionTitle")}</h2>
          {data.attention.length === 0 ? (
            <p className="all-clear">
              <CheckCircle2 size={18} aria-hidden /> {t("allClear")}
            </p>
          ) : (
            <ul>
              {data.attention.map((item, i) => (
                <AttentionItem key={i} item={item} />
              ))}
            </ul>
          )}
        </section>
      )}
      {op && (
        <section className="tiles" aria-label={t("latestPlan")}>
          <Tile label={t("kServed")} value={s ? `${number(s.served)} / ${number(s.confirmed)}` : "—"} />
          <Tile label={t("kOffers")} value={s ? `${number(s.offers_taken)} / ${number(s.offered)}` : "—"} />
          <Tile label={t("kEmpty")} value={s?.empty_share != null ? `${number(Math.round(s.empty_share * 100))}%` : "—"} />
          <Tile label={t("kContribution")} value={s && s.revenue_minor !== null && s.cost_minor !== null ? money(s.revenue_minor - s.cost_minor) : "—"} />
          <Tile label={t("trucks")} value={number(op.trucks)} />
          <Tile label={t("waitingOrders")} value={number(op.waiting)} />
        </section>
      )}
      {data?.latest && (
        <p className="muted small">
          {t("latestPlan")}: {date(data.latest.created_at)}
          {data.latest.created_by ? ` · ${data.latest.created_by}` : ""} · <Link to="/history">{t("allPlans")}</Link>
        </p>
      )}
    </>
  );
}

function AttentionItem({ item }: { item: Attention }) {
  const { t, number, date } = useI18n();
  const { canPlan } = useAuth();
  const action = ACTIONS[item.kind];
  const Icon = action.level === "warn" ? AlertTriangle : Info;
  let text: string;
  switch (item.kind) {
    case "unserved":
    case "notify":
      text = `${number(item.count)} ${t(`at_${item.kind}`)}`;
      break;
    case "idle_trucks":
      text = `${number(item.count)} ${t("at_idle_trucks")} ${item.names.join(", ")}${item.count > item.names.length ? "…" : ""}`;
      break;
    case "expired":
      text = `${number(item.count)} ${t("at_expired")} ${item.refs.join(", ")}${item.count > item.refs.length ? "…" : ""}`;
      break;
    case "released":
      text = `${t("at_released")} ${item.refs.join(", ")}`;
      break;
    case "plan_invalid":
      text = `${t("at_plan_invalid")} ${item.findings.join(", ")}`;
      break;
    case "window_behind":
      text = `${t("at_window_behind")} ${date(item.start)}`;
      break;
    default:
      text = t(`at_${item.kind}`);
  }
  // Viewers see the item but not actions they cannot take.
  const actionable = canPlan || action.label === "goBoard";
  return (
    <li className={`attention-item ${action.level}`}>
      <Icon size={17} aria-hidden />
      <span>{text}</span>
      {actionable && (
        <Link className="btn" to={action.to}>
          {t(action.label)}
        </Link>
      )}
    </li>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value overview-value">{value}</div>
    </div>
  );
}
