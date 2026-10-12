"use client";

import { useMemo, useState } from "react";
import {
  ArrowRight,
  LockKeyhole,
  Search,
  Truck,
  UnlockKeyhole,
} from "lucide-react";
import {
  apiBase,
  localInput,
  riyadhISO,
  send,
  type Job,
  type Plan,
  type Run,
  type Workspace,
} from "@/lib/api";
import { useLocale } from "@/lib/locale";
import { Badge, Empty, Modal, RevisionNotice } from "./ui";

type Props = {
  workspace: Workspace;
  run: Run | null;
  changed: () => Promise<void>;
  act: (fn: () => Promise<void>) => Promise<void>;
  busy: boolean;
};

export function PlanningBoard({ workspace, run, changed, act, busy }: Props) {
  const { t, lang, money, num, time, date } = useLocale();
  const [view, setView] = useState<"candidate" | "baseline">("candidate");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<Job | null>(null);
  const [locking, setLocking] = useState<Job | null>(null);
  const snapshot =
    run?.result && run.snapshot ? run.snapshot : workspace.snapshot;
  const plan = run?.result?.[view];
  const stale = !!run?.result && run.revision !== workspace.version;
  const assignments = useMemo(
    () => new Map(plan?.assignments.map((a) => [a.job_id, a])),
    [plan],
  );
  const site = (id: string) => {
    const s = snapshot.sites.find((s) => s.id === id);
    return (
      (lang === "ar" && s?.name_ar ? s.name_ar : s?.name)?.replace(
        / · (Demo.*|Synthetic.*)| · تجريبي/g,
        "",
      ) ?? id
    );
  };
  const jobs = snapshot.jobs.filter((j) =>
    `${j.reference} ${j.customer} ${j.id}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const comparison = run?.result?.comparison;
  const confirmed = snapshot.jobs.filter((j) => j.state === "confirmed").length;
  const currentJob = (id: string) =>
    workspace.snapshot.jobs.find((j) => j.id === id) ?? null;

  return (
    <>
      {stale && (
        <div className="notice warn">
          {t(
            `Showing saved revision ${run?.revision}. Current inputs are revision ${workspace.version}; plan again to include your changes.`,
            `تعرض النسخة المحفوظة ${run?.revision}. المدخلات الحالية هي النسخة ${workspace.version}؛ أعد التخطيط لتضمين التغييرات.`,
          )}
        </div>
      )}
      <div className="metrics">
        <div className="metric">
          <span>{t("Confirmed work covered", "تغطية الأعمال المؤكدة")}</span>
          <strong>
            {plan ? plan.assignments.length : "—"}
            <small> / {confirmed}</small>
          </strong>
          <p>
            <i
              className={
                plan?.coverage === "complete" && plan.valid
                  ? "dot green"
                  : "dot"
              }
            />
            {plan
              ? plan.coverage === "complete"
                ? t("All obligations assigned", "تم إسناد جميع الالتزامات")
                : t(
                    "Partial coverage · review unserved work",
                    "تغطية جزئية · راجع الأعمال غير المسندة",
                  )
              : t("Ready for first plan", "جاهز للخطة الأولى")}
          </p>
        </div>
        <div className="metric">
          <span>
            {t("Modeled operating cost", "التكلفة التشغيلية المقدّرة")}
          </span>
          <strong>
            {plan?.valid ? money(plan.costs?.total_minor) : "—"}
            <small> SAR</small>
          </strong>
          <p>
            {t("Distance + resource duty time", "المسافة + وقت تشغيل الموارد")}
          </p>
        </div>
        <div className="metric">
          <span>
            {t("Difference from greedy baseline", "الفرق عن الخطة المرجعية")}
          </span>
          <strong
            className={
              (comparison?.modeled_saving_minor ?? 0) > 0 ? "teal" : ""
            }
          >
            {money(
              comparison?.modeled_saving_minor == null
                ? null
                : Math.abs(comparison.modeled_saving_minor),
            )}
            <small> SAR</small>
          </strong>
          <p>
            {comparison?.comparable
              ? comparison.modeled_saving_minor === 0
                ? t(
                    "No modeled cost change",
                    "لا يوجد تغير في التكلفة المقدّرة",
                  )
                : (comparison.modeled_saving_minor ?? 0) > 0
                  ? t(
                      "Estimated reduction · same inputs",
                      "انخفاض تقديري · نفس المدخلات",
                    )
                  : t(
                      "Estimated increase · same inputs",
                      "ارتفاع تقديري · نفس المدخلات",
                    )
              : t(
                  "A matching valid comparison is required",
                  "يلزم توفر خطتين صالحتين للمقارنة",
                )}
          </p>
        </div>
        <div className="metric">
          <span>{t("Empty running", "المسافة دون حمولة")}</span>
          <strong>
            {plan?.valid
              ? num((plan.costs?.empty_distance_m ?? 0) / 1000)
              : "—"}
            <small> {t("km", "كم")}</small>
          </strong>
          <p>
            {t(
              "Includes required return movements",
              "تشمل رحلات العودة المطلوبة",
            )}
          </p>
        </div>
      </div>
      {plan && (
        <div className="plan-strip">
          <div>
            <Badge
              tone={
                plan.valid
                  ? plan.coverage === "complete"
                    ? "good"
                    : "warn"
                  : "bad"
              }
            >
              {plan.valid
                ? t("Independently validated", "تم التحقق بشكل مستقل")
                : t("No validated solution", "لا يوجد حل صالح")}
            </Badge>
            <span>
              {outcomeLabel(plan, lang)} · {num(plan.runtime_ms / 1000)}{" "}
              {t("s", "ث")}
            </span>
          </div>
          <span>
            {t("Input fingerprint", "بصمة المدخلات")}{" "}
            <code>{plan.snapshot_hash.slice(0, 10)}</code>
          </span>
        </div>
      )}
      {!!plan?.findings.length && (
        <div className="notice bad">
          <strong>
            {t("Review before using this plan", "راجع الخطة قبل استخدامها")}
          </strong>
          <ul>
            {plan.findings.slice(0, 8).map((f, i) => (
              <li key={i}>
                {f.message} {f.entity_ids.join(", ")}
              </li>
            ))}
          </ul>
        </div>
      )}
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t("Dispatch plan", "خطة التوزيع")}</h2>
            <p>
              {t(
                "Every job. Every resource. One reviewed plan.",
                "كل شحنة وكل مورد ضمن خطة تخضع للمراجعة.",
              )}
            </p>
          </div>
          {run?.result && (
            <div className="segmented">
              <button
                className={view === "candidate" ? "active" : ""}
                onClick={() => setView("candidate")}
              >
                {t("Optimized", "المحسّنة")}
              </button>
              <button
                className={view === "baseline" ? "active" : ""}
                onClick={() => setView("baseline")}
              >
                {t("Greedy baseline", "المرجعية")}
              </button>
            </div>
          )}
        </div>
        <div className="table-toolbar">
          <label className="search">
            <Search size={16} />
            <input
              aria-label={t("Search jobs", "البحث عن شحنات")}
              placeholder={t(
                "Search reference or customer…",
                "ابحث بالمرجع أو العميل…",
              )}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <span>
            {jobs.length} {t("jobs", "شحنات")} ·{" "}
            {t("Riyadh time (UTC+3)", "توقيت الرياض (+٣)")}
          </span>
        </div>
        <div className="table-scroll">
          <table className="jobs-table">
            <thead>
              <tr>
                <th>{t("Job / customer", "الشحنة / العميل")}</th>
                <th>{t("Route", "المسار")}</th>
                <th>{t("Pickup window", "نافذة الاستلام")}</th>
                <th>{t("Equipment", "المعدات")}</th>
                <th>{t("Assignment", "الإسناد")}</th>
                <th>{t("Review", "مراجعة")}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const assignment = assignments.get(job.id);
                const lock = workspace.snapshot.locks.find(
                  (l) => l.job_id === job.id,
                );
                return (
                  <tr
                    key={job.id}
                    className={
                      plan && !assignment && job.state === "confirmed"
                        ? "unserved"
                        : ""
                    }
                  >
                    <td>
                      <button
                        className="text-button job-reference"
                        onClick={() => setEditing(currentJob(job.id))}
                      >
                        {job.reference}
                      </button>
                      <div className="subtle small">{job.customer}</div>
                    </td>
                    <td>
                      <div className="route-name">
                        {site(job.pickup_site_id)} <ArrowRight size={13} />{" "}
                        {site(job.delivery_site_id)}
                      </div>
                      <div className="subtle small">
                        {t("Priority", "الأولوية")} {job.priority} ·{" "}
                        {num(job.weight_kg / 1000)} {t("tonnes", "طن")}
                      </div>
                    </td>
                    <td>
                      <span className="nowrap">
                        {time(job.pickup_window.start)} –{" "}
                        {time(job.pickup_window.end)}
                      </span>
                      <div className="subtle small">
                        {date(job.pickup_window.start)}
                      </div>
                    </td>
                    <td>
                      <Badge>
                        {job.equipment === "dry_van"
                          ? t("Dry van", "مقطورة مغلقة")
                          : t("Flatbed", "سطحة")}
                      </Badge>
                    </td>
                    <td>
                      {assignment ? (
                        <>
                          <div className="assignment">
                            <Truck size={14} />
                            {
                              snapshot.teams.find(
                                (x) => x.id === assignment.team_id,
                              )?.name
                            }
                          </div>
                          <div className="subtle small">
                            {time(assignment.pickup_at)} →{" "}
                            {time(assignment.delivery_at)}
                          </div>
                        </>
                      ) : (
                        <Badge
                          tone={
                            plan && job.state === "confirmed"
                              ? "warn"
                              : "neutral"
                          }
                        >
                          {job.state === "offered"
                            ? t("Offered", "معروضة")
                            : job.state === "cancelled"
                              ? t("Cancelled", "ملغاة")
                              : plan
                                ? t("Unserved", "غير مسندة")
                                : t("Unplanned", "لم تُخطط")}
                        </Badge>
                      )}
                    </td>
                    <td>
                      <button
                        className={`icon-button ${lock ? "locked" : ""}`}
                        disabled={busy || job.state !== "confirmed"}
                        onClick={() => setLocking(currentJob(job.id))}
                        aria-label={`${lock ? t("Edit lock", "تعديل القفل") : t("Set assignment lock", "تثبيت الإسناد")} ${job.reference}`}
                      >
                        {lock ? (
                          <LockKeyhole size={17} />
                        ) : (
                          <UnlockKeyhole size={17} />
                        )}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!jobs.length && (
            <Empty title={t("No matching jobs", "لا توجد شحنات مطابقة")}>
              {t(
                "Try another reference or customer name.",
                "جرّب مرجعاً أو اسم عميل آخر.",
              )}
            </Empty>
          )}
        </div>
        <div className="panel-footer">
          <span>
            {t(
              "Fixed tractor, trailer and driver teams",
              "فرق ثابتة من الشاحنة والمقطورة والسائق",
            )}
          </span>
          <a className="text-button" href={apiBase() + "/api/templates/jobs"}>
            {t("Export current input CSV", "تصدير المدخلات الحالية CSV")} ↗
          </a>
        </div>
      </section>
      <Timeline plan={plan} snapshot={snapshot} />
      {run?.result && (
        <details className="panel details">
          <summary>
            {t(
              "Cost assumptions & comparison details",
              "افتراضات التكلفة وتفاصيل المقارنة",
            )}
          </summary>
          <div className="details-grid">
            <div>
              <p>
                {t("Distance cost", "تكلفة المسافة")}:{" "}
                <strong>{money(plan?.costs?.distance_minor)} SAR</strong>
              </p>
              <p>
                {t("Duty cost", "تكلفة وقت التشغيل")}:{" "}
                <strong>{money(plan?.costs?.duty_minor)} SAR</strong>
              </p>
              <p>
                {t(
                  "Soft preference penalty (excluded from cash)",
                  "غرامة تفضيل مرن (ليست تكلفة نقدية)",
                )}
                : {money(plan?.objective_penalty_minor)} SAR
              </p>
            </div>
            <div>
              <p>
                {t("Excluded", "المستثنى")}:{" "}
                {plan?.costs?.exclusions.join(", ")}
              </p>
              <p>
                {t("Changes vs baseline", "التغييرات مقابل المرجع")}:{" "}
                {comparison?.changed_assignments}
              </p>
              {comparison?.reasons.map((r) => (
                <p key={r}>{r}</p>
              ))}
              <p>
                {t(
                  "This baseline is a deterministic greedy heuristic, not actual historical dispatch. These are modeled costs, not realized savings.",
                  "الخطة المرجعية خوارزمية تقريبية وليست توزيعاً تاريخياً فعلياً. التكاليف مقدّرة وليست وفورات محققة.",
                )}
              </p>
            </div>
          </div>
          {plan?.valid && (
            <p>
              <a
                className="text-button"
                href={apiBase() + `/api/runs/${run.id}/export?method=${view}`}
              >
                {t(
                  "Download this reviewed plan (CSV)",
                  "تنزيل هذه الخطة المراجعة (CSV)",
                )}{" "}
                ↗
              </a>
            </p>
          )}
        </details>
      )}
      {editing && (
        <JobEditor
          job={editing}
          workspace={workspace}
          close={() => setEditing(null)}
          save={(job, expectedVersion) =>
            act(async () => {
              await send(
                `/api/jobs/${job.id}`,
                { expected_version: expectedVersion, job },
                "PUT",
              );
              setEditing(null);
              await changed();
            })
          }
          busy={busy}
        />
      )}
      {locking && (
        <LockEditor
          job={locking}
          workspace={workspace}
          assignment={assignments.get(locking.id)}
          close={() => setLocking(null)}
          save={(teamId, pickup, expectedVersion) =>
            act(async () => {
              const locks = workspace.snapshot.locks.filter(
                (l) => l.job_id !== locking.id,
              );
              if (teamId)
                locks.push({
                  job_id: locking.id,
                  team_id: teamId,
                  pickup_at: pickup || null,
                });
              await send(
                "/api/locks",
                { expected_version: expectedVersion, locks },
                "PUT",
              );
              setLocking(null);
              await changed();
            })
          }
          busy={busy}
        />
      )}
    </>
  );
}

function outcomeLabel(plan: Plan, lang: string) {
  const labels: Record<string, [string, string]> = {
    optimal: ["Optimal within this model", "أمثل ضمن هذا النموذج"],
    feasible: ["Feasible · optimality not proven", "صالح · لم تثبت الأمثلية"],
    unknown: [
      "Search limit reached · feasibility unknown",
      "انتهى وقت البحث · الجدوى غير معروفة",
    ],
    proven_infeasible: [
      "Proven infeasible under these inputs",
      "ثبت عدم الجدوى لهذه المدخلات",
    ],
    model_invalid: ["Input or model error", "خطأ في المدخلات أو النموذج"],
  };
  if (plan.method === "baseline")
    return lang === "ar" ? "مرجع تقريبي حتمي" : "Deterministic greedy baseline";
  return labels[plan.outcome]?.[lang === "ar" ? 1 : 0];
}

function Timeline({
  plan,
  snapshot,
}: {
  plan?: Plan;
  snapshot: Workspace["snapshot"];
}) {
  const { t, time, date } = useLocale();
  const origin = new Date(snapshot.horizon.start).getTime();
  const end = Math.max(
    new Date(snapshot.horizon.end).getTime(),
    ...(plan?.activities ?? []).map((a) => new Date(a.end).getTime()),
  );
  const span = end - origin;
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>{t("Resource timeline", "الجدول الزمني للموارد")}</h2>
          <p>
            {t(
              "Occupancy includes travel, service, waiting and return.",
              "تشمل مدة الإشغال التنقل والخدمة والانتظار والعودة.",
            )}
          </p>
        </div>
        <div className="legend">
          <span>
            <i className="legend-dot loaded" />
            {t("Loaded / service", "حمولة / خدمة")}
          </span>
          <span>
            <i className="legend-dot empty-travel" />
            {t("Empty", "دون حمولة")}
          </span>
          <span>
            <i className="legend-dot waiting" />
            {t("Waiting", "انتظار")}
          </span>
        </div>
      </div>
      {!plan?.activities.length ? (
        <Empty
          title={t("A clear view of the day ahead", "رؤية واضحة ليوم العمل")}
        >
          {t(
            "Run the planner to see team movements and resource occupancy.",
            "شغّل المخطط لعرض تحركات الفرق وإشغال الموارد.",
          )}
        </Empty>
      ) : (
        <div className="timeline-scroll">
          <div className="timeline">
            <div className="timeline-header">
              <span>{t("Team", "الفريق")}</span>
              <div>
                {[0, 1, 2, 3, 4].map((i) => (
                  <span key={i}>
                    {date(new Date(origin + (span * i) / 4).toISOString())} ·{" "}
                    {time(new Date(origin + (span * i) / 4).toISOString())}
                  </span>
                ))}
              </div>
            </div>
            {snapshot.teams.map((team) => (
              <div className="timeline-row" key={team.id}>
                <div>
                  <strong>{team.name}</strong>
                  <span>
                    {team.tractor_id} · {team.driver_id}
                  </span>
                </div>
                <div className="timeline-track">
                  {plan.activities
                    .filter((a) => a.team_id === team.id)
                    .map((a, i) => (
                      <div
                        key={i}
                        className={`activity ${a.kind}`}
                        style={{
                          insetInlineStart: `${((new Date(a.start).getTime() - origin) / span) * 100}%`,
                          width: `${Math.max(0.2, ((new Date(a.end).getTime() - new Date(a.start).getTime()) / span) * 100)}%`,
                        }}
                        title={`${a.kind} · ${a.job_id ?? ""} · ${date(a.start)} ${time(a.start)}–${time(a.end)}`}
                      />
                    ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function JobEditor({
  job,
  workspace,
  close,
  save,
  busy,
}: {
  job: Job;
  workspace: Workspace;
  close: () => void;
  save: (job: Job, version: number) => Promise<void>;
  busy: boolean;
}) {
  const { t } = useLocale();
  const [draft, setDraft] = useState(job);
  const [baseVersion] = useState(workspace.version);
  return (
    <Modal
      title={`${t("Review job", "مراجعة الشحنة")} · ${job.reference}`}
      close={close}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save(draft, baseVersion);
        }}
      >
        <RevisionNotice base={baseVersion} current={workspace.version} />
        <p className="subtle">
          {t(
            "Edit current inputs. Existing plan results remain tied to their saved revision.",
            "عدّل المدخلات الحالية. تبقى نتائج الخطط السابقة مرتبطة بنسخها المحفوظة.",
          )}
        </p>
        <div className="form-grid">
          <label>
            {t("Customer", "العميل")}
            <input
              required
              value={draft.customer}
              onChange={(e) => setDraft({ ...draft, customer: e.target.value })}
            />
          </label>
          <label>
            {t("Weight (kg)", "الوزن (كغ)")}
            <input
              required
              type="number"
              min="1"
              max="100000"
              value={draft.weight_kg}
              onChange={(e) =>
                setDraft({ ...draft, weight_kg: Number(e.target.value) })
              }
            />
          </label>
          <label>
            {t("Priority", "الأولوية")}
            <select
              value={draft.priority}
              onChange={(e) =>
                setDraft({ ...draft, priority: Number(e.target.value) })
              }
            >
              {[1, 2, 3].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label>
            {t("Status", "الحالة")}
            <select
              value={draft.state}
              onChange={(e) =>
                setDraft({ ...draft, state: e.target.value as Job["state"] })
              }
            >
              <option value="confirmed">{t("Confirmed", "مؤكدة")}</option>
              <option value="offered">{t("Offered", "معروضة")}</option>
              <option value="cancelled">{t("Cancelled", "ملغاة")}</option>
            </select>
          </label>
          {(["pickup", "delivery"] as const).map((kind) => (
            <fieldset key={kind}>
              <legend>
                {kind === "pickup"
                  ? t("Pickup · Riyadh time", "الاستلام · توقيت الرياض")
                  : t("Delivery · Riyadh time", "التسليم · توقيت الرياض")}
              </legend>
              <select
                aria-label={kind + " site"}
                value={draft[`${kind}_site_id`]}
                onChange={(e) =>
                  setDraft({ ...draft, [`${kind}_site_id`]: e.target.value })
                }
              >
                {workspace.snapshot.sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              {(["start", "end"] as const).map((bound) => (
                <label key={bound}>
                  {bound === "start" ? t("From", "من") : t("Until", "إلى")}
                  <input
                    required
                    type="datetime-local"
                    value={localInput(draft[`${kind}_window`][bound])}
                    onChange={(e) => {
                      if (e.target.value)
                        setDraft({
                          ...draft,
                          [`${kind}_window`]: {
                            ...draft[`${kind}_window`],
                            [bound]: riyadhISO(e.target.value),
                          },
                        });
                    }}
                  />
                </label>
              ))}
            </fieldset>
          ))}
          <label>
            {t("Delivery window means", "معنى نافذة التسليم")}
            <select
              value={draft.delivery_window_kind}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  delivery_window_kind: e.target
                    .value as Job["delivery_window_kind"],
                })
              }
            >
              <option value="completion">
                {t("Unloading completion", "اكتمال التفريغ")}
              </option>
              <option value="service_start">
                {t("Unloading start", "بداية التفريغ")}
              </option>
            </select>
          </label>
        </div>
        <div className="modal-actions">
          <button type="button" className="button" onClick={close}>
            {t("Cancel", "إلغاء")}
          </button>
          <button
            className="button primary"
            disabled={busy || baseVersion !== workspace.version}
          >
            {t("Save reviewed inputs", "حفظ المدخلات المراجعة")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function LockEditor({
  job,
  workspace,
  assignment,
  close,
  save,
  busy,
}: {
  job: Job;
  workspace: Workspace;
  assignment?: Plan["assignments"][number];
  close: () => void;
  save: (team: string, pickup: string, version: number) => Promise<void>;
  busy: boolean;
}) {
  const { t } = useLocale();
  const lock = workspace.snapshot.locks.find((l) => l.job_id === job.id);
  const [baseVersion] = useState(workspace.version);
  const [team, setTeam] = useState(
    lock?.team_id ?? assignment?.team_id ?? workspace.snapshot.teams[0].id,
  );
  const [exact, setExact] = useState(!!lock?.pickup_at);
  const [pickup, setPickup] = useState(
    localInput(
      lock?.pickup_at ?? assignment?.pickup_at ?? job.pickup_window.start,
    ),
  );
  return (
    <Modal
      title={`${t("Assignment lock", "تثبيت الإسناد")} · ${job.reference}`}
      close={close}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save(team, exact ? riyadhISO(pickup) : "", baseVersion);
        }}
      >
        <RevisionNotice base={baseVersion} current={workspace.version} />
        <p className="subtle">
          {t(
            "Require a team, optionally at an exact pickup time. The next plan must honor this lock or report a conflict.",
            "حدد فريقاً ويمكنك تثبيت وقت الاستلام. يجب أن تلتزم الخطة التالية بهذا القيد أو تبلغ عن تعارض.",
          )}
        </p>
        <label>
          {t("Required team", "الفريق المطلوب")}
          <select value={team} onChange={(e) => setTeam(e.target.value)}>
            {workspace.snapshot.teams.map((t) => (
              <option value={t.id} key={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={exact}
            onChange={(e) => setExact(e.target.checked)}
          />
          {t("Also lock pickup time", "تثبيت وقت الاستلام أيضاً")}
        </label>
        {exact && (
          <label>
            {t("Pickup · Riyadh time", "الاستلام · توقيت الرياض")}
            <input
              type="datetime-local"
              required
              value={pickup}
              onChange={(e) => setPickup(e.target.value)}
            />
          </label>
        )}
        <div className="modal-actions">
          {lock && (
            <button
              type="button"
              className="button danger"
              disabled={busy || baseVersion !== workspace.version}
              onClick={() => void save("", "", baseVersion)}
            >
              {t("Remove lock", "إزالة التثبيت")}
            </button>
          )}
          <button
            className="button primary"
            disabled={busy || baseVersion !== workspace.version}
          >
            {t("Save lock", "حفظ التثبيت")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
