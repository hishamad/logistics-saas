// Today: where the day stands, a way to ask, the plan, what needs the dispatcher, the network.
import { Check } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Attention, type Network, type OverviewData, type PlanRun } from "../api";
import { useAuth } from "../auth";
import { AskBar } from "../components/AskBar";
import { NetworkMap } from "../components/NetworkMap";
import { PlanOrbit } from "../components/PlanOrbit";
import { useI18n, type StringKey } from "../i18n";
import { useCountUp } from "../motion";

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
  const { t, fill, date, count } = useI18n();
  const { me } = useAuth();
  const [data, setData] = useState<OverviewData | null>(null);
  const [network, setNetwork] = useState<Network | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .get<OverviewData>("/api/overview")
      .then(setData)
      .catch((caught: Error) => setError(caught.message));
  }, []);
  const latestId = data?.latest?.id;
  useEffect(load, [load]);
  useEffect(() => {
    api
      .get<Network>("/api/network")
      .then(setNetwork)
      .catch(() => setNetwork(null));
  }, [latestId]);
  // Every 15 s normally; every 1.5 s while the engine works, so the result arrives promptly.
  const running = !!data?.running;
  useEffect(() => {
    const id = setInterval(load, running ? 1500 : 15000);
    return () => clearInterval(id);
  }, [load, running]);

  const kinds = new Set(data?.attention.map((a) => a.kind));
  const planned = !!data?.latest && !kinds.has("plan_out_of_date") && !kinds.has("no_plan");
  const warns = data?.attention.filter((a) => ACTIONS[a.kind].level === "warn").length ?? 0;
  const steps: { label: StringKey; state: "done" | "now" | "todo" }[] = [
    { label: "stepOrders", state: (data?.operation.contract ?? 0) > 0 ? "done" : "now" },
    { label: "stepPlan", state: running ? "now" : planned ? "done" : "now" },
    { label: "stepReview", state: planned && !running ? (warns ? "now" : "done") : "todo" },
    { label: "stepDrivers", state: planned && !running && !warns ? "now" : "todo" },
  ];
  // Suggestions use the carrier's own orders and trucks, never made-up ones.
  const unserved = data?.attention.find((a) => a.kind === "unserved");
  const idle = data?.attention.find((a) => a.kind === "idle_trucks");
  const suggestions = [
    unserved?.kind === "unserved" && unserved.refs?.[0] ? fill("askWhyChip", { ref: unserved.refs[0] }) : null,
    idle?.kind === "idle_trucks" && idle.names[0] ? fill("askRuleChip", { truck: idle.names[0].replace(/^Team /, "") }) : null,
  ].filter((s): s is string => !!s);

  return (
    <>
      <header className="today-head">
        <div>
          <span className="muted small">{date(new Date().toISOString(), { dateStyle: "full", timeStyle: undefined })}</span>
          <h1>{fill(greeting(), { name: me?.user.name.split(" ")[0] ?? "" })}</h1>
        </div>
        <ol className="stepper" aria-label={t("dayLabel")}>
          {steps.map((step, i) => (
            <li key={step.label} className={step.state}>
              <span className="step-dot">{step.state === "done" ? <Check size={11} strokeWidth={3} aria-hidden /> : i + 1}</span>
              {t(step.label)}
            </li>
          ))}
        </ol>
      </header>
      {error && <div className="alert alert-error">{error}</div>}
      <AskBar runId={latestId ?? null} suggestions={suggestions} />
      {data && (
        <div className="today-grid">
          <section className="panel network-panel" aria-label={t("networkTitle")}>
            <div className="panel-head">
              <div>
                <h2>{t("networkTitle")}</h2>
                <span className="muted small">
                  {count("trucks", data.operation.trucks)} · {count("orders", data.operation.contract + data.operation.spot)}
                </span>
              </div>
              <div className="map-legend">
                <span>
                  <i className="key k-loaded" />
                  {t("legendLoaded")}
                </span>
                <span>
                  <i className="key k-empty" />
                  {t("legendEmpty")}
                </span>
              </div>
            </div>
            {network && network.sites.length > 0 ? (
              <NetworkMap network={network} />
            ) : (
              <p className="empty">{t("networkNone")}</p>
            )}
            {network && network.lanes.length === 0 && network.sites.length > 0 && <p className="muted small">{t("networkNoPlan")}</p>}
          </section>
          <div className="today-side">
            <PlanCard data={data} onStarted={load} />
            <section className="panel attention" aria-label={t("attentionTitle")}>
              <h2>{t("attentionTitle")}</h2>
              {data.attention.length === 0 ? (
                <p className="all-clear">
                  <Check size={17} aria-hidden /> {t("allClear")}
                </p>
              ) : (
                <ul>
                  {data.attention.map((item, i) => (
                    <AttentionItem key={i} item={item} />
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      )}
    </>
  );
}

function greeting(): StringKey {
  const hour = Number(new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: "Asia/Riyadh" }).format(new Date()));
  return hour < 12 ? "greetMorning" : hour < 17 ? "greetAfternoon" : "greetEvening";
}

function PlanCard({ data, onStarted }: { data: OverviewData; onStarted: () => void }) {
  const { t, fill, number } = useI18n();
  const { canPlan } = useAuth();
  const [error, setError] = useState("");
  const hours = Math.round((new Date(data.operation.window.end).getTime() - new Date(data.operation.window.start).getTime()) / 3600000);
  const due = data.operation.contract + data.operation.spot - data.operation.waiting;
  const outdated = data.attention.some((a) => a.kind === "plan_out_of_date");

  async function plan() {
    setError("");
    try {
      await api.post<PlanRun>("/api/plans", { seconds: 30 });
      onStarted();
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  if (data.running) {
    return (
      <section className="panel plan-card" aria-label={t("planTitleShort")}>
        <PlanOrbit startedAt={data.running.created_at} seconds={data.running.settings.seconds} orders={due} trucks={data.operation.trucks} />
      </section>
    );
  }
  const latest = data.latest;
  if (latest?.summary && !outdated) return <PlanResult run={latest} onAgain={canPlan ? plan : null} />;
  return (
    <section className="panel plan-card fade" aria-label={t("planTitleShort")}>
      <span className="kicker">{fill("planKickerHours", { hours: number(hours) })}</span>
      <h2 className="plan-title">{outdated ? t("planOutdated") : t("planReady")}</h2>
      <p className="muted">{fill("planReadySub", { orders: number(due), trucks: number(data.operation.trucks) })}</p>
      {error && <div className="alert alert-error">{error}</div>}
      {canPlan ? (
        <div className="result-actions">
          <button type="button" className="btn btn-primary btn-large" onClick={plan}>
            {fill("planButtonHours", { hours: number(hours) })} <span aria-hidden="true" className="flip-rtl">→</span>
          </button>
          <span className="muted small">{t("planHint")}</span>
        </div>
      ) : (
        <p className="muted small">{t("viewerCannotPlan")}</p>
      )}
    </section>
  );
}

function PlanResult({ run, onAgain }: { run: PlanRun; onAgain: (() => void) | null }) {
  const { t, number, money } = useI18n();
  const s = run.summary!;
  const served = useCountUp(s.served);
  const offers = useCountUp(s.offers_taken);
  const empty = useCountUp(Math.round((s.empty_share ?? 0) * 100));
  const contribution = useCountUp(s.revenue_minor !== null && s.cost_minor !== null ? s.revenue_minor - s.cost_minor : 0);
  const figures = [
    { label: t("kServed"), value: `${number(Math.round(served))} / ${number(s.confirmed)}` },
    { label: t("kOffers"), value: `${number(Math.round(offers))} / ${number(s.offered)}` },
    { label: t("kEmpty"), value: s.empty_share !== null ? `${number(Math.round(empty))}%` : "—" },
    { label: t("kContribution"), value: s.revenue_minor !== null ? money(Math.round(contribution / 100) * 100) : "—" },
  ];
  return (
    <section className="panel plan-card" aria-label={t("planTitleShort")}>
      <div className="plan-result-head fade">
        <span className={s.valid ? "check ok" : "check bad"}>
          <Check size={15} strokeWidth={2.4} aria-hidden /> {s.valid ? t("passed") : t("planFailed")}
        </span>
        <span style={{ display: "flex", gap: 16 }}>
          {onAgain && (
            <button type="button" className="text-btn" onClick={onAgain}>
              {t("planAgain")} <span className="arrow" aria-hidden="true">↻</span>
            </button>
          )}
          <Link to="/board" className="text-btn">
            {t("openBoard")} <span className="arrow flip-rtl" aria-hidden="true">→</span>
          </Link>
        </span>
      </div>
      <div className="figures">
        {figures.map((f, i) => (
          <div key={f.label} className="figure rise" style={{ animationDelay: `${120 + i * 90}ms` }}>
            <span className="label">{f.label}</span>
            <span className="value">{f.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function AttentionItem({ item }: { item: Attention }) {
  const { t, number, date } = useI18n();
  const { canPlan } = useAuth();
  const action = ACTIONS[item.kind];
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
      <span className="attention-dot" aria-hidden="true" />
      <span>{text}</span>
      {actionable && (
        <Link className="text-btn" to={action.to}>
          {t(action.label)} <span className="arrow flip-rtl" aria-hidden="true">→</span>
        </Link>
      )}
    </li>
  );
}
