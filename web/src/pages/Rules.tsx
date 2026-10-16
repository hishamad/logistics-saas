// Steering: rules by form or by an Arabic/English sentence, and frozen jobs.
// A sentence only ever produces a proposal; the dispatcher adds it explicitly.
import { Lock, MessageSquareText, Plus, Snowflake, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type Interpretation, type Rule, type RuleKind, type Steering } from "../api";
import { useAuth } from "../auth";
import { useI18n, type StringKey } from "../i18n";
import { addHours, fromRiyadhInput, toRiyadhInput } from "../time";

type NewRule = Omit<Rule, "id" | "source_text"> & { source_text?: string };

export function useRuleText(steering: Steering | null) {
  const { fill, date, money, lang } = useI18n();
  return (rule: Rule | NewRule) => {
    if (!steering) return "";
    const team = steering.teams.find((t) => t.id === rule.team_id || t.tractor_id === rule.resource_id);
    const truck = team?.name ?? rule.resource_id ?? rule.team_id ?? "?";
    const job = steering.jobs.find((j) => j.id === rule.job_id)?.reference ?? rule.job_id ?? "?";
    const site = steering.sites.find((s) => s.id === rule.site_id);
    const siteName = site ? (lang === "ar" && site.name_ar ? site.name_ar : site.name) : (rule.site_id ?? "?");
    const when = (iso?: string) => (iso ? date(iso) : "?");
    switch (rule.kind) {
      case "resource_unavailable":
        return fill("descUnavailable", { truck, from: when(rule.window?.start), until: when(rule.window?.end) });
      case "required_end":
        return fill("descRequiredEnd", { truck, site: siteName, by: when(rule.window?.end) });
      case "customer_eligibility":
        return fill("descCustomer", { truck, customer: rule.customer ?? "?" });
      case "preferred_assignment":
        return rule.strength === "soft"
          ? fill("descAssignSoft", { job, truck, penalty: money(rule.penalty_minor) })
          : fill("descAssignHard", { job, truck });
    }
  };
}

export function Rules() {
  const { t } = useI18n();
  const { canPlan } = useAuth();
  const [steering, setSteering] = useState<Steering | null>(null);
  const [error, setError] = useState("");
  const editable = canPlan;

  const load = useCallback(() => {
    api
      .get<Steering>("/api/steering")
      .then(setSteering)
      .catch((caught: Error) => setError(caught.message));
  }, []);
  useEffect(load, [load]);

  async function act(action: () => Promise<unknown>) {
    setError("");
    try {
      await action();
      load();
      return true;
    } catch (caught) {
      setError((caught as Error).message);
      return false;
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("rulesTitle")}</h1>
          <span className="muted">{t("rulesLead")}</span>
        </div>
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {!editable && <div className="alert alert-info">{t("viewerSteer")}</div>}
      {steering && (
        <div className="rules-grid">
          {editable && <Ask steering={steering} onAdd={(rule) => act(() => api.post("/api/rules", rule))} />}
          {editable && <RuleForm steering={steering} onAdd={(rule) => act(() => api.post("/api/rules", rule))} />}
          <ActiveRules steering={steering} editable={editable} onRemove={(id) => act(() => api.del(`/api/rules/${id}`))} />
          <Frozen steering={steering} editable={editable} act={act} />
        </div>
      )}
    </>
  );
}

function Ask({ steering, onAdd }: { steering: Steering; onAdd: (rule: NewRule) => Promise<boolean> }) {
  const { t } = useI18n();
  const describe = useRuleText(steering);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<Interpretation | null>(null);

  async function interpret() {
    setBusy(true);
    setAnswer(null);
    try {
      setAnswer(await api.post<Interpretation>("/api/rules/interpret", { text }));
    } catch (caught) {
      setAnswer({ status: "error", explanation: (caught as Error).message, rule: null });
    } finally {
      setBusy(false);
    }
  }

  async function add(rule: Rule) {
    const { id: _, ...rest } = rule;
    if (await onAdd(rest)) {
      setAnswer(null);
      setText("");
    }
  }

  return (
    <section className="panel rules-wide">
      <h2>
        <MessageSquareText size={18} aria-hidden /> {t("askTitle")}
      </h2>
      {!steering.ai && <p className="muted">{t("aiOff")}</p>}
      <div className="ask">
        <textarea className="input" rows={2} dir="auto" placeholder={t("askPlaceholder")} value={text} onChange={(e) => setText(e.target.value)} disabled={!steering.ai} />
        <button className="btn btn-primary" onClick={interpret} disabled={!steering.ai || busy || text.trim().length < 2}>
          {busy ? t("interpreting") : t("askButton")}
        </button>
      </div>
      {answer && answer.status === "proposed" && answer.rule && (
        <div className="alert alert-ok result">
          <b>{t("proposal")}:</b> {describe(answer.rule)}
          <div className="muted" dir="auto">
            {answer.explanation}
          </div>
          <div className="result-actions">
            <button className="btn btn-primary" onClick={() => add(answer.rule!)}>
              {t("addThisRule")}
            </button>
            <button className="btn" onClick={() => setAnswer(null)}>
              {t("discard")}
            </button>
          </div>
        </div>
      )}
      {answer && answer.status !== "proposed" && (
        <div className={`alert ${answer.status === "error" ? "alert-error" : "alert-warn"} result`} dir="auto">
          <b>{answer.status === "error" ? t("aiError") : t("clarify")}</b> {answer.question || answer.explanation}
        </div>
      )}
    </section>
  );
}

const KINDS: { kind: RuleKind; label: StringKey }[] = [
  { kind: "resource_unavailable", label: "kindUnavailable" },
  { kind: "required_end", label: "kindRequiredEnd" },
  { kind: "customer_eligibility", label: "kindCustomer" },
  { kind: "preferred_assignment", label: "kindAssign" },
];

function RuleForm({ steering, onAdd }: { steering: Steering; onAdd: (rule: NewRule) => Promise<boolean> }) {
  const { t, lang } = useI18n();
  const teams = [...steering.teams].sort((a, b) => a.name.localeCompare(b.name, "en", { numeric: true }));
  const [kind, setKind] = useState<RuleKind>("resource_unavailable");
  const [team, setTeam] = useState(teams[0]?.id ?? "");
  const [from, setFrom] = useState(toRiyadhInput(steering.horizon.start));
  const [until, setUntil] = useState(toRiyadhInput(addHours(steering.horizon.start, 24)));
  const [site, setSite] = useState(steering.sites[0]?.id ?? "");
  const [customer, setCustomer] = useState(steering.customers[0] ?? "");
  const [job, setJob] = useState("");
  const [strength, setStrength] = useState<"hard" | "soft">("hard");
  const [penalty, setPenalty] = useState(500);

  function build(): NewRule {
    const chosen = steering.teams.find((x) => x.id === team);
    const base = { resource_id: null, team_id: null, job_id: null, site_id: null, customer: null, window: null, strength: "hard" as const, penalty_minor: 0 };
    switch (kind) {
      case "resource_unavailable":
        return { ...base, kind, resource_id: chosen?.tractor_id ?? null, window: { start: fromRiyadhInput(from), end: fromRiyadhInput(until) } };
      case "required_end":
        return { ...base, kind, team_id: team, site_id: site, window: { start: steering.horizon.start, end: fromRiyadhInput(until) } };
      case "customer_eligibility":
        return { ...base, kind, team_id: team, customer };
      case "preferred_assignment":
        return { ...base, kind, team_id: team, job_id: job, strength, penalty_minor: strength === "soft" ? Math.round(penalty * 100) : 0 };
    }
  }

  const ready = team && (kind !== "preferred_assignment" || job) && (kind !== "resource_unavailable" || (from && until && until > from));
  return (
    <section className="panel">
      <h2>
        <Plus size={18} aria-hidden /> {t("formTitle")}
      </h2>
      <div className="form-grid">
        <label className="field">
          <span>{t("ruleKind")}</span>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as RuleKind)}>
            {KINDS.map((k) => (
              <option key={k.kind} value={k.kind}>
                {t(k.label)}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{t("fieldTruck")}</span>
          <select className="input" value={team} onChange={(e) => setTeam(e.target.value)}>
            {teams.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
        {kind === "resource_unavailable" && (
          <>
            <label className="field">
              <span>{t("fieldFrom")}</span>
              <input className="input" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label className="field">
              <span>{t("fieldUntil")}</span>
              <input className="input" type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
            </label>
          </>
        )}
        {kind === "required_end" && (
          <>
            <label className="field">
              <span>{t("fieldSite")}</span>
              <select className="input" value={site} onChange={(e) => setSite(e.target.value)}>
                {steering.sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {lang === "ar" && s.name_ar ? s.name_ar : s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>{t("fieldBy")}</span>
              <input className="input" type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
            </label>
          </>
        )}
        {kind === "customer_eligibility" && (
          <label className="field">
            <span>{t("fieldCustomer")}</span>
            <select className="input" value={customer} onChange={(e) => setCustomer(e.target.value)}>
              {steering.customers.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
        )}
        {kind === "preferred_assignment" && (
          <>
            <label className="field">
              <span>{t("fieldJob")}</span>
              <input className="input" list="job-refs" value={steering.jobs.find((j) => j.id === job)?.reference ?? job} onChange={(e) => setJob(steering.jobs.find((j) => j.reference === e.target.value)?.id ?? e.target.value)} />
              <datalist id="job-refs">
                {steering.jobs.map((j) => (
                  <option key={j.id} value={j.reference}>
                    {j.customer}
                  </option>
                ))}
              </datalist>
            </label>
            <label className="field">
              <span>{t("fieldStrength")}</span>
              <select className="input" value={strength} onChange={(e) => setStrength(e.target.value as "hard" | "soft")}>
                <option value="hard">{t("hard")}</option>
                <option value="soft">{t("soft")}</option>
              </select>
            </label>
            {strength === "soft" && (
              <label className="field">
                <span>{t("fieldPenalty")}</span>
                <input className="input" type="number" min={1} value={penalty} onChange={(e) => setPenalty(Number(e.target.value))} />
              </label>
            )}
          </>
        )}
      </div>
      <button className="btn btn-primary" disabled={!ready} onClick={() => void onAdd(build())}>
        {t("addRule")}
      </button>
    </section>
  );
}

function ActiveRules({ steering, editable, onRemove }: { steering: Steering; editable: boolean; onRemove: (id: string) => void }) {
  const { t } = useI18n();
  const describe = useRuleText(steering);
  return (
    <section className="panel">
      <h2>{t("activeRules")}</h2>
      {steering.rules.length === 0 ? (
        <p className="empty">{t("noRules")}</p>
      ) : (
        <ul className="rule-list">
          {steering.rules.map((rule) => (
            <li key={rule.id}>
              <div>
                <b>{describe(rule)}</b>
                {rule.source_text && rule.source_text !== "Rule form" && (
                  <div className="muted" dir="auto">
                    {t("saidAs")} “{rule.source_text}”
                  </div>
                )}
              </div>
              {editable && (
                <button className="btn btn-ghost" onClick={() => onRemove(rule.id)} aria-label={t("remove")}>
                  <Trash2 size={16} aria-hidden />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">{t("nextPlanNote")}</p>
    </section>
  );
}

function Frozen({ steering, editable, act }: { steering: Steering; editable: boolean; act: (action: () => Promise<unknown>) => Promise<boolean> }) {
  const { t, number } = useI18n();
  const [hours, setHours] = useState(24);
  const [note, setNote] = useState("");
  const names = new Map(steering.teams.map((x) => [x.id, x.name]));
  const refs = new Map(steering.jobs.map((j) => [j.id, j]));
  const locks = [...steering.locks].sort((a, b) => (names.get(a.team_id) ?? "").localeCompare(names.get(b.team_id) ?? "", "en", { numeric: true }));

  async function freeze() {
    setNote("");
    let result = { added: 0, accepted: 0 };
    const ok = await act(async () => {
      result = await api.post<{ added: number; accepted: number }>("/api/locks/freeze", { run_id: steering.latest_plan, hours });
    });
    if (ok) setNote(`${number(result.added)} ${t("frozenAdded")}${result.accepted ? ` ${number(result.accepted)} ${t("spotAccepted")}.` : ""}`);
  }

  return (
    <section className="panel">
      <h2>
        <Snowflake size={18} aria-hidden /> {t("frozenTitle")}
        {locks.length > 0 && <span className="badge">{number(locks.length)}</span>}
      </h2>
      <p className="muted">{t("frozenLead")}</p>
      {editable && (
        <div className="freeze-row">
          <span>{t("freezeNext")}</span>
          <select className="input" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {[6, 12, 24, 48, 72].map((h) => (
              <option key={h} value={h}>
                {number(h)}
              </option>
            ))}
          </select>
          <span>{t("hoursOfPlan")}</span>
          <button className="btn btn-primary" onClick={freeze} disabled={!steering.latest_plan}>
            {t("freeze")}
          </button>
          {!steering.latest_plan && <span className="muted">{t("noPlanToFreeze")}</span>}
          {note && <span className="ok-text">{note}</span>}
        </div>
      )}
      {locks.length === 0 ? (
        <p className="empty">{t("noFrozen")}</p>
      ) : (
        <>
          <ul className="rule-list lock-list">
            {locks.map((lock) => (
              <li key={lock.job_id}>
                <span>
                  <Lock size={13} aria-hidden /> <b>{refs.get(lock.job_id)?.reference ?? lock.job_id}</b> <span className="muted">{refs.get(lock.job_id)?.customer}</span> → {names.get(lock.team_id) ?? lock.team_id}
                </span>
                {editable && (
                  <button className="btn btn-ghost" onClick={() => void act(() => api.del(`/api/locks/${lock.job_id}`))}>
                    {t("unfreeze")}
                  </button>
                )}
              </li>
            ))}
          </ul>
          {editable && (
            <button className="btn" onClick={() => void act(() => api.del("/api/locks"))}>
              {t("unfreezeAll")}
            </button>
          )}
        </>
      )}
    </section>
  );
}
