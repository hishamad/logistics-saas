"use client";

import { useRef, useState } from "react";
import { Check, Plus, Sparkles, Trash2 } from "lucide-react";
import {
  localInput,
  ApiError,
  riyadhISO,
  send,
  type Proposal,
  type Rule,
  type Workspace,
} from "@/lib/api";
import { useLocale } from "@/lib/locale";
import { Badge, Modal, RevisionNotice } from "./ui";

export function RulesPanel({
  workspace,
  changed,
  act,
  busy,
}: {
  workspace: Workspace;
  changed: () => Promise<void>;
  act: (fn: () => Promise<void>) => Promise<void>;
  busy: boolean;
}) {
  const { t } = useLocale();
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [manual, setManual] = useState(false);
  const requestIdentity = useRef({ signature: "", key: "" });
  const interpret = () =>
    act(async () => {
      setProposal(null);
      const signature = JSON.stringify([
        workspace.snapshot.tenant_id,
        workspace.version,
        text.trim(),
      ]);
      if (requestIdentity.current.signature !== signature)
        requestIdentity.current = { signature, key: crypto.randomUUID() };
      try {
        setProposal(
          await send<Proposal>("/api/rule-proposals", {
            expected_version: workspace.version,
            text,
            idempotency_key: requestIdentity.current.key,
          }),
        );
        requestIdentity.current = { signature: "", key: "" };
      } catch (error) {
        // A known provider failure ends this attempt. A transport timeout may
        // hide a successful response, so keep its identity for a safe retry.
        if (
          error instanceof ApiError &&
          (error.attemptComplete ||
            (error.status < 500 && error.status !== 409))
        )
          requestIdentity.current = { signature: "", key: "" };
        throw error;
      }
    });
  return (
    <aside className="rules-panel panel">
      <div className="rules-title">
        <span className="spark">
          <Sparkles size={19} />
        </span>
        <div>
          <h2>{t("Your operating rules", "قواعد التشغيل")}</h2>
          <p>{t("Explain. Review. Replan.", "اشرح، راجع، وأعد التخطيط.")}</p>
        </div>
      </div>
      <div className="rules-content">
        <p className="subtle">
          {t(
            "Tell the planner what changed, in Arabic or English. You approve the interpretation before it affects a plan.",
            "أخبر المخطط بالتغييرات بالعربية أو الإنجليزية. تعتمد التفسير قبل أن يؤثر على الخطة.",
          )}
        </p>
        {!workspace.ai_configured && (
          <div className="notice compact">
            {t(
              "AI setup pending. Use the structured rule form below to keep planning.",
              "إعداد الذكاء الاصطناعي قيد الانتظار. استخدم نموذج القواعد لمواصلة التخطيط.",
            )}
          </div>
        )}
        <label className="sr-only" htmlFor="rule-instruction">
          {t("Dispatcher instruction", "تعليمات الموزّع")}
        </label>
        <textarea
          id="rule-instruction"
          dir="auto"
          rows={5}
          maxLength={2000}
          placeholder={t(
            "e.g. Assign SFD-1041 to Team 02.",
            "مثال: أسند SFD-1041 إلى Team 02.",
          )}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button
          className="button primary full"
          disabled={busy || !workspace.ai_configured || text.trim().length < 3}
          onClick={() => void interpret()}
        >
          <Sparkles size={15} />
          {t("Interpret instruction", "تفسير التعليمات")}
        </button>
        <p className="micro">
          {t(
            "AI proposes rules. The deterministic planner checks feasibility and cost.",
            "يقترح الذكاء الاصطناعي القواعد. ويتحقق المخطط الحتمي من الجدوى والتكلفة.",
          )}
        </p>
        {proposal && (
          <div className="proposal">
            <Badge tone={proposal.status === "proposed" ? "good" : "warn"}>
              {proposal.status === "proposed"
                ? t("Ready for review", "جاهز للمراجعة")
                : t(
                    "Needs clarification or unsupported",
                    "يلزم التوضيح أو الطلب غير مدعوم",
                  )}
            </Badge>
            <p dir="auto">{proposal.explanation}</p>
            {proposal.question && (
              <p dir="auto">
                <strong>{proposal.question}</strong>
              </p>
            )}
            {proposal.rule && (
              <RuleSummary rule={proposal.rule} workspace={workspace} />
            )}
            <p className="micro">
              {proposal.model}{" "}
              {proposal.latency_ms != null &&
                `· ${(proposal.latency_ms / 1000).toFixed(1)}s`}
            </p>
            {proposal.rule && (
              <button
                className="button primary full"
                disabled={busy || proposal.base_version !== workspace.version}
                onClick={() =>
                  void act(async () => {
                    await send(`/api/rule-proposals/${proposal.id}/approve`, {
                      expected_version: workspace.version,
                    });
                    setProposal(null);
                    setText("");
                    await changed();
                  })
                }
              >
                <Check size={15} />
                {t("Approve this rule", "اعتماد هذه القاعدة")}
              </button>
            )}
            {proposal.base_version !== workspace.version && (
              <p className="small">
                {t(
                  "Inputs changed. Interpret the instruction again.",
                  "تغيرت المدخلات. أعد تفسير التعليمات.",
                )}
              </p>
            )}
          </div>
        )}
        <div className="rule-divider">
          <h3>
            {t("Approved rules", "القواعد المعتمدة")}{" "}
            <span>{workspace.snapshot.rules.length}</span>
          </h3>
          <button
            className="icon-button"
            aria-label={t("Add structured rule", "إضافة قاعدة منظمة")}
            onClick={() => setManual(true)}
            disabled={busy}
          >
            <Plus size={17} />
          </button>
        </div>
        {workspace.snapshot.rules.length === 0 && (
          <p className="subtle small">
            {t(
              "No extra rules yet. Resource calendars, job windows, equipment and depot returns already apply.",
              "لا توجد قواعد إضافية. تسري بالفعل قيود التقويم ونوافذ الشحنات والمعدات والعودة للمستودع.",
            )}
          </p>
        )}
        {workspace.snapshot.rules.map((rule) => (
          <div className="approved-rule" key={rule.id}>
            <div className="row-between">
              <Badge tone={rule.strength === "hard" ? "neutral" : "warn"}>
                {rule.strength === "hard"
                  ? t("Required", "إلزامية")
                  : t("Preference", "تفضيل")}
              </Badge>
              <button
                className="icon-button"
                aria-label={`${t("Remove rule", "إزالة القاعدة")} ${rule.id}`}
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    await send(
                      `/api/rules/${rule.id}`,
                      { expected_version: workspace.version },
                      "DELETE",
                    );
                    await changed();
                  })
                }
              >
                <Trash2 size={14} />
              </button>
            </div>
            <RuleSummary rule={rule} workspace={workspace} />
          </div>
        ))}
        <button
          className="button full"
          disabled={busy}
          onClick={() => setManual(true)}
        >
          <Plus size={15} />
          {t("Add a structured rule", "إضافة قاعدة منظمة")}
        </button>
        <div className="rule-note">
          <Check size={16} />
          <p>
            {t(
              "Approving a rule changes the next planning run. Saved plans stay unchanged.",
              "يؤثر اعتماد القاعدة على التخطيط التالي. تبقى الخطط المحفوظة كما هي.",
            )}
          </p>
        </div>
      </div>
      {manual && (
        <ManualRule
          workspace={workspace}
          close={() => setManual(false)}
          busy={busy}
          save={(rule, expectedVersion) =>
            act(async () => {
              await send("/api/rules", {
                expected_version: expectedVersion,
                rule,
              });
              setManual(false);
              await changed();
            })
          }
        />
      )}
    </aside>
  );
}

export function RuleSummary({
  rule,
  workspace,
}: {
  rule: Rule;
  workspace: Workspace;
}) {
  const { t, time, date, money, lang } = useLocale();
  const s = workspace.snapshot;
  const team = s.teams.find((x) => x.id === rule.team_id)?.name ?? rule.team_id;
  const resource =
    s.resources.find((x) => x.id === rule.resource_id)?.name ??
    rule.resource_id;
  const job =
    s.jobs.find((x) => x.id === rule.job_id)?.reference ?? rule.job_id;
  const site = s.sites.find((x) => x.id === rule.site_id);
  return (
    <div className="rule-summary">
      {rule.kind === "resource_unavailable" && (
        <p>
          <strong>{resource}</strong> {t("unavailable", "غير متاح")}
        </p>
      )}
      {rule.kind === "required_end" && (
        <p>
          <strong>{team}</strong> {t("must finish at", "يجب أن ينهي العمل في")}{" "}
          <strong>{lang === "ar" ? site?.name_ar : site?.name}</strong>
        </p>
      )}
      {rule.kind === "customer_eligibility" && (
        <p>
          <strong>{team}</strong> {t("can serve only", "يخدم فقط")}{" "}
          <strong>{rule.customer}</strong>
        </p>
      )}
      {rule.kind === "preferred_assignment" && (
        <p>
          <strong>{job}</strong> → <strong>{team}</strong>
          {rule.strength === "soft" && (
            <span className="small">
              {" "}
              · {t("Penalty", "الغرامة")} {money(rule.penalty_minor)} SAR
            </span>
          )}
        </p>
      )}
      {rule.window && (
        <p className="small subtle">
          {rule.kind === "required_end"
            ? t("By", "قبل")
            : `${date(rule.window.start)} ${time(rule.window.start)} →`}{" "}
          {date(rule.window.end)} {time(rule.window.end)} ·{" "}
          {t("Riyadh", "الرياض")}
        </p>
      )}
    </div>
  );
}

function ManualRule({
  workspace,
  close,
  save,
  busy,
}: {
  workspace: Workspace;
  close: () => void;
  save: (rule: Rule, version: number) => Promise<void>;
  busy: boolean;
}) {
  const { t } = useLocale();
  const s = workspace.snapshot;
  const [baseVersion] = useState(workspace.version);
  const [kind, setKind] = useState<Rule["kind"]>("preferred_assignment");
  const [ruleId] = useState(() => crypto.randomUUID());
  const [team, setTeam] = useState(s.teams[0].id);
  const [resource, setResource] = useState(s.resources[0].id);
  const [job, setJob] = useState(
    s.jobs.find((j) => j.state === "confirmed")?.id ?? "",
  );
  const [site, setSite] = useState(s.sites[0].id);
  const [customer, setCustomer] = useState(s.jobs[0]?.customer ?? "");
  const [start, setStart] = useState(localInput(s.horizon.start));
  const [end, setEnd] = useState(localInput(s.horizon.end));
  const [soft, setSoft] = useState(false);
  const [penalty, setPenalty] = useState("50");
  const names: [Rule["kind"], string][] = [
    [
      "preferred_assignment",
      t("Assign a job to a team", "إسناد شحنة إلى فريق"),
    ],
    ["resource_unavailable", t("Resource unavailable", "عدم توفر مورد")],
    ["required_end", t("Required end location", "موقع نهاية العمل المطلوب")],
    [
      "customer_eligibility",
      t("Restrict team to one customer", "تخصيص الفريق لعميل واحد"),
    ],
  ];
  const build = (): Rule => ({
    id: ruleId,
    kind,
    strength: kind === "preferred_assignment" && soft ? "soft" : "hard",
    penalty_minor:
      kind === "preferred_assignment" && soft
        ? Math.round(Number(penalty) * 100)
        : 0,
    source_text: "Reviewed structured rule",
    ...(kind === "resource_unavailable"
      ? {
          resource_id: resource,
          window: { start: riyadhISO(start), end: riyadhISO(end) },
        }
      : { team_id: team }),
    ...(kind === "required_end"
      ? {
          site_id: site,
          window: { start: s.horizon.start, end: riyadhISO(end) },
        }
      : {}),
    ...(kind === "preferred_assignment" ? { job_id: job } : {}),
    ...(kind === "customer_eligibility" ? { customer } : {}),
  });
  return (
    <Modal
      title={t("Review a new operating rule", "مراجعة قاعدة تشغيل جديدة")}
      close={close}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save(build(), baseVersion);
        }}
      >
        <RevisionNotice base={baseVersion} current={workspace.version} />
        <label>
          {t("Rule type", "نوع القاعدة")}
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as Rule["kind"])}
          >
            {names.map(([v, label]) => (
              <option value={v} key={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <div className="form-grid">
          {kind !== "resource_unavailable" ? (
            <label>
              {t("Team", "الفريق")}
              <select value={team} onChange={(e) => setTeam(e.target.value)}>
                {s.teams.map((t) => (
                  <option value={t.id} key={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label>
              {t("Resource", "المورد")}
              <select
                value={resource}
                onChange={(e) => setResource(e.target.value)}
              >
                {s.resources.map((r) => (
                  <option value={r.id} key={r.id}>
                    {r.name} · {r.kind}
                  </option>
                ))}
              </select>
            </label>
          )}
          {kind === "preferred_assignment" && (
            <>
              <label>
                {t("Job", "الشحنة")}
                <select
                  required
                  value={job}
                  onChange={(e) => setJob(e.target.value)}
                >
                  {s.jobs
                    .filter((j) => j.state === "confirmed")
                    .map((j) => (
                      <option key={j.id} value={j.id}>
                        {j.reference}
                      </option>
                    ))}
                </select>
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={soft}
                  onChange={(e) => setSoft(e.target.checked)}
                />
                {t(
                  "Allow another team with a penalty",
                  "السماح بفريق آخر مع غرامة",
                )}
              </label>
              {soft && (
                <label>
                  {t(
                    "Penalty (SAR, not a cash cost)",
                    "الغرامة (ريال، ليست تكلفة نقدية)",
                  )}
                  <input
                    required
                    type="number"
                    min="0"
                    max="10000"
                    step="0.01"
                    value={penalty}
                    onChange={(e) => setPenalty(e.target.value)}
                  />
                </label>
              )}
            </>
          )}
          {kind === "required_end" && (
            <label>
              {t("Required final site", "موقع النهاية المطلوب")}
              <select value={site} onChange={(e) => setSite(e.target.value)}>
                {s.sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {kind === "customer_eligibility" && (
            <label>
              {t("Only this customer", "هذا العميل فقط")}
              <select
                value={customer}
                onChange={(e) => setCustomer(e.target.value)}
              >
                {[...new Set(s.jobs.map((j) => j.customer))].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
          )}
          {kind === "resource_unavailable" && (
            <label>
              {t("Unavailable from · Riyadh", "غير متاح من · الرياض")}
              <input
                type="datetime-local"
                required
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
          )}
          {(kind === "resource_unavailable" || kind === "required_end") && (
            <label>
              {kind === "required_end"
                ? t("Arrive by · Riyadh", "الوصول قبل · الرياض")
                : t("Unavailable until · Riyadh", "غير متاح حتى · الرياض")}
              <input
                type="datetime-local"
                required
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
          )}
        </div>
        <div className="notice">
          {kind === "required_end"
            ? t(
                "This replaces the team’s default return to its starting depot. Early arrival is allowed.",
                "يستبدل هذا شرط العودة لمستودع البداية. يُسمح بالوصول المبكر.",
              )
            : kind === "customer_eligibility"
              ? t(
                  "This team can only serve the selected customer. Other teams can still serve that customer.",
                  "يخدم هذا الفريق العميل المحدد فقط، ويمكن للفرق الأخرى خدمة العميل نفسه.",
                )
              : t(
                  "The next optimization will check this rule against all existing commitments.",
                  "ستتحقق عملية التحسين التالية من القاعدة مقابل جميع الالتزامات الحالية.",
                )}
        </div>
        <div className="modal-actions">
          <button type="button" className="button" onClick={close}>
            {t("Cancel", "إلغاء")}
          </button>
          <button
            disabled={busy || baseVersion !== workspace.version}
            className="button primary"
          >
            <Check size={15} />
            {t("Approve rule", "اعتماد القاعدة")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
