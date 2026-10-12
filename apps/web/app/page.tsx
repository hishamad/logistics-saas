"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  CheckCheck,
  ChevronDown,
  CircleHelp,
  Clock3,
  FileInput,
  Globe2,
  History,
  LayoutDashboard,
  LoaderCircle,
  LogOut,
  Play,
  RefreshCw,
  Route,
  Settings2,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { api, ApiError, send, type Run, type Workspace } from "@/lib/api";
import { LocaleContext, useLocale, type Language } from "@/lib/locale";
import { PlanningBoard } from "@/components/planning-board";
import { RulesPanel } from "@/components/rules-panel";
import { ImportPanel } from "@/components/import-panel";
import { AssumptionsPanel } from "@/components/assumptions-panel";
import { Badge, Empty } from "@/components/ui";

type View = "planning" | "imports" | "rules" | "history" | "assumptions";

export default function Page() {
  const [lang, setLang] = useState<Language>("en");
  useEffect(() => {
    try {
      if (localStorage.getItem("freight-language") === "ar") setLang("ar");
    } catch {
      /* Browser storage can be disabled; language still works in memory. */
    }
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    try {
      localStorage.setItem("freight-language", lang);
    } catch {
      /* Optional persistence. */
    }
  }, [lang]);
  return (
    <LocaleContext value={lang}>
      <Dashboard setLang={setLang} />
    </LocaleContext>
  );
}

function Dashboard({ setLang }: { setLang: (lang: Language) => void }) {
  const { t, lang, date, time } = useLocale();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("planning");
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [help, setHelp] = useState(false);
  const [authMode, setAuthMode] = useState<"demo" | "production" | null>(null);
  const pendingRunIdentity = useRef({ signature: "", key: "" });
  const sessionEpoch = useRef(0);
  const refreshEpoch = useRef(0);
  const actionLock = useRef(false);
  const clearSession = useCallback(() => {
    sessionEpoch.current++;
    setWorkspace(null);
    setSelectedRun(null);
    setActiveRun(null);
    setRuns([]);
    setView("planning");
    pendingRunIdentity.current = { signature: "", key: "" };
  }, []);

  const refresh = useCallback(async () => {
    const session = sessionEpoch.current;
    const refreshId = ++refreshEpoch.current;
    const [ws, history] = await Promise.all([
      api<Workspace>("/api/workspace"),
      api<Run[]>("/api/runs"),
    ]);
    if (session !== sessionEpoch.current || refreshId !== refreshEpoch.current)
      return [];
    setWorkspace(ws);
    setRuns(history);
    setActiveRun(
      history.find((r) => r.state === "queued" || r.state === "running") ??
        null,
    );
    return history;
  }, []);
  const act = useCallback(
    async (fn: () => Promise<void>) => {
      if (actionLock.current) return;
      actionLock.current = true;
      setBusy(true);
      setError("");
      try {
        await fn();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        if (e instanceof ApiError && e.status === 401) {
          clearSession();
        }
      } finally {
        setBusy(false);
        actionLock.current = false;
      }
    },
    [clearSession],
  );
  useEffect(() => {
    let alive = true;
    const session = sessionEpoch.current;
    void api<{ mode: "demo" | "production" }>("/api/auth/config")
      .then((config) => {
        if (alive) setAuthMode(config.mode);
        return refresh();
      })
      .then(async (history) => {
        const last = history.find((r) => r.state === "succeeded");
        if (last) {
          const full = await api<Run>(`/api/runs/${last.id}`);
          if (alive && session === sessionEpoch.current) setSelectedRun(full);
        }
      })
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 401))
          setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setReady(true);
      });
    return () => {
      alive = false;
    };
  }, [refresh]);
  useEffect(() => {
    if (!activeRun) return;
    let alive = true;
    const session = sessionEpoch.current;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      let again = true;
      try {
        const run = await api<Run>(`/api/runs/${activeRun.id}`, {
          signal: AbortSignal.any([
            controller.signal,
            AbortSignal.timeout(15000),
          ]),
        });
        if (!alive || session !== sessionEpoch.current) return;
        if (run.state === "queued" || run.state === "running")
          setActiveRun(run);
        else {
          if (run.state === "succeeded") setSelectedRun(run);
          if (run.error) setError(run.error);
          await refresh();
          again = false;
        }
      } catch (e) {
        if (!alive || session !== sessionEpoch.current) return;
        if (e instanceof ApiError && e.status === 401) {
          again = false;
          clearSession();
        }
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (again && alive && session === sessionEpoch.current)
          timer = setTimeout(poll, 1200);
      }
    };
    timer = setTimeout(poll, 1200);
    return () => {
      alive = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [activeRun?.id]); // One poller per durable run, never one per rendered progress update.
  const changed = async () => {
    await refresh();
  };
  const login = (tenantId: string) =>
    act(async () => {
      clearSession();
      await send("/api/session", { tenant_id: tenantId });
      setSelectedRun(null);
      const history = await refresh();
      const last = history.find((r) => r.state === "succeeded");
      if (last) setSelectedRun(await api<Run>(`/api/runs/${last.id}`));
    });
  const solve = (diagnostic = false) =>
    act(async () => {
      if (!workspace) return;
      const signature = `${workspace.snapshot.tenant_id}:${workspace.version}:${diagnostic}`;
      if (pendingRunIdentity.current.signature !== signature)
        pendingRunIdentity.current = { signature, key: crypto.randomUUID() };
      const queued = await send<{ id: string }>("/api/runs", {
        expected_version: workspace.version,
        diagnostic,
        seconds: workspace.snapshot.jobs.length > 40 ? 30 : 10,
        idempotency_key: pendingRunIdentity.current.key,
      });
      pendingRunIdentity.current = { signature: "", key: "" };
      setActiveRun(await api<Run>(`/api/runs/${queued.id}`));
      setView("planning");
      setRuns(await api<Run[]>("/api/runs"));
    });
  const navigation: [View, React.ReactNode, string][] = [
    [
      "planning",
      <LayoutDashboard size={19} key="planning" />,
      t("Planning board", "لوحة التخطيط"),
    ],
    [
      "imports",
      <FileInput size={19} key="imports" />,
      t("Data imports", "استيراد البيانات"),
    ],
    [
      "rules",
      <Sparkles size={19} key="rules" />,
      t("Operating rules", "قواعد التشغيل"),
    ],
    [
      "history",
      <History size={19} key="history" />,
      t("Plan history", "سجل الخطط"),
    ],
    [
      "assumptions",
      <Settings2 size={19} key="assumptions" />,
      t("Assumptions", "الافتراضات"),
    ],
  ];

  if (!ready)
    return (
      <div className="loading-page">
        <Route size={36} />
        <LoaderCircle className="spin" />
        <p>
          {t("Opening your planning workspace…", "جارٍ فتح مساحة التخطيط…")}
        </p>
      </div>
    );
  if (!workspace)
    return (
      <main className="welcome">
        <div className="welcome-art">
          <div className="brand">
            <Route />
            <span>
              MADAR<span className="brand-ar">مدار</span>
            </span>
          </div>
          <div>
            <p className="eyebrow">
              {t("FREIGHT PLANNING, MADE CLEAR", "تخطيط شحن واضح")}
            </p>
            <h1>
              {t(
                "A better plan starts with the whole picture.",
                "تبدأ الخطة الأفضل برؤية الصورة كاملة.",
              )}
            </h1>
            <p>
              {t(
                "Turn freight, fleet capacity and everyday constraints into a plan your team can inspect and trust.",
                "حوّل الشحنات وسعة الأسطول والقيود اليومية إلى خطة يمكن لفريقك فحصها والاعتماد عليها.",
              )}
            </p>
          </div>
          <div className="welcome-footer">
            <ShieldCheck size={18} />
            {t(
              "Reviewed rules. Deterministic planning. Traceable decisions.",
              "قواعد مراجعة وتخطيط حتمي وقرارات قابلة للتتبع.",
            )}
          </div>
        </div>
        <div className="welcome-card">
          <button
            className="button language"
            onClick={() => setLang(lang === "en" ? "ar" : "en")}
          >
            <Globe2 size={16} />
            {lang === "en" ? "العربية" : "English"}
          </button>
          <Badge tone="good">
            {authMode === "production"
              ? t("SECURE WORKSPACE", "مساحة عمل آمنة")
              : t("LOCAL DEMO", "نسخة تجريبية محلية")}
          </Badge>
          <h2>{t("Step into the planning room", "ادخل غرفة التخطيط")}</h2>
          <p>
            {authMode === "production"
              ? t(
                  "Sign in to review your organization's jobs, planning assumptions and proposed plans.",
                  "سجّل الدخول لمراجعة شحنات مؤسستك وافتراضات التخطيط والخطط المقترحة.",
                )
              : t(
                  "Explore a synthetic Saudi freight scenario. Each workspace has its own records and history.",
                  "استكشف سيناريو شحن سعودي تجريبياً. لكل مساحة سجلاتها وتاريخها المستقل.",
                )}
          </p>
          {error && (
            <div role="alert" className="notice bad">
              {error}
            </div>
          )}
          {authMode === "production" && (
            <a className="button primary full" href="/api/auth/login">
              {t(
                "Sign in with your organization",
                "تسجيل الدخول بحساب المؤسسة",
              )}
            </a>
          )}
          {authMode === null && (
            <button className="button" onClick={() => window.location.reload()}>
              {t("Retry connection", "إعادة الاتصال")}
            </button>
          )}
          {authMode === "demo" &&
            [
              ["eastern-demo", t("Eastern Freight", "الشحن الشرقي")],
              ["western-demo", t("Western Freight", "الشحن الغربي")],
            ].map(([id, name]) => (
              <button
                disabled={busy}
                key={id}
                className="workspace-choice"
                onClick={() => void login(id)}
              >
                <span className="workspace-icon">
                  <Route size={22} />
                </span>
                <span>
                  <strong>{name}</strong>
                  <small>
                    {t(
                      "4 fixed teams · 8 demo jobs",
                      "٤ فرق ثابتة · ٨ شحنات تجريبية",
                    )}
                  </small>
                </span>
                <ArrowRight size={20} />
              </button>
            ))}
          <p className="micro">
            {t(
              "Planning and review only. Workspace access requires authorization; this application does not publish dispatch instructions.",
              "للتخطيط والمراجعة فقط. يتطلب الوصول تصريحاً ولا ينشر التطبيق تعليمات توزيع فعلية.",
            )}
          </p>
        </div>
      </main>
    );

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Route size={28} />
          <span>
            MADAR<span className="brand-ar">مدار</span>
          </span>
        </div>
        <div className="workspace-label">
          <span className="avatar">{workspace.name[0]}</span>
          <div>
            <strong>{workspace.name.replace(" · Demo", "")}</strong>
            <span>
              {workspace.snapshot.mode === "demo"
                ? t("Synthetic workspace", "مساحة تجريبية")
                : t("Review workspace", "مساحة المراجعة")}
            </span>
          </div>
          <ChevronDown size={14} />
        </div>
        <p className="nav-label">{t("WORKSPACE", "مساحة العمل")}</p>
        <nav>
          {navigation.map(([key, icon, label]) => (
            <button
              key={key}
              className={view === key ? "active" : ""}
              onClick={() => setView(key)}
            >
              {icon}
              <span>{label}</span>
              {key === "rules" && workspace.snapshot.rules.length > 0 && (
                <b>{workspace.snapshot.rules.length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="demo-label">
            <span className="dot green" />
            <strong>
              {workspace.snapshot.mode === "demo"
                ? t("Demo mode", "وضع تجريبي")
                : t("Shadow planning", "تخطيط للمراجعة")}
            </strong>
            <p>
              {t(
                "Plan and review. No live dispatch.",
                "خطط وراجع. لا يوجد توزيع فعلي.",
              )}
            </p>
          </div>
          <button className="sidebar-action" onClick={() => setHelp(!help)}>
            <CircleHelp size={17} />
            {t("How planning works", "كيف يعمل التخطيط")}
          </button>
          <button
            className="sidebar-action"
            onClick={() =>
              void act(async () => {
                await api("/api/session", { method: "DELETE" });
                clearSession();
              })
            }
          >
            <LogOut size={17} />
            {authMode === "production"
              ? t("Sign out", "تسجيل الخروج")
              : t("Switch workspace", "تبديل المساحة")}
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span className="breadcrumb">
            {t("Operations", "العمليات")} <span>/</span>{" "}
            <strong>{navigation.find((n) => n[0] === view)?.[2]}</strong>
          </span>
          <div className="topbar-actions">
            <span className="timezone">
              <Clock3 size={14} />
              {t("Asia / Riyadh", "آسيا / الرياض")}
            </span>
            <button
              className="button language"
              onClick={() => setLang(lang === "en" ? "ar" : "en")}
            >
              <Globe2 size={15} />
              {lang === "en" ? "العربية" : "English"}
            </button>
            <span className="user-avatar">DP</span>
          </div>
        </header>
        <main className="content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                {t(
                  `${workspace.name} · PLANNING WORKSPACE`,
                  `${workspace.name} · مساحة التخطيط`,
                )}
              </p>
              <h1>
                {view === "planning"
                  ? t("See the day. Shape the plan.", "راقب يومك، وارسم خطتك.")
                  : navigation.find((n) => n[0] === view)?.[2]}
              </h1>
              <p>
                {date(workspace.snapshot.horizon.start)} —{" "}
                {date(workspace.snapshot.horizon.end)} ·{" "}
                {t(
                  `${(Date.parse(workspace.snapshot.horizon.end) - Date.parse(workspace.snapshot.horizon.start)) / 3600000}-hour scenario`,
                  `سيناريو ${(Date.parse(workspace.snapshot.horizon.end) - Date.parse(workspace.snapshot.horizon.start)) / 3600000} ساعة`,
                )}{" "}
                · {t("Revision", "النسخة")} {workspace.version}
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="button icon-only"
                aria-label={t("Refresh workspace", "تحديث المساحة")}
                disabled={busy}
                onClick={() => void act(changed)}
              >
                <RefreshCw size={17} />
              </button>
              <button
                className="button primary"
                disabled={busy || workspace.role === "viewer" || !!activeRun}
                onClick={() => void solve()}
              >
                {activeRun ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <Play size={16} />
                )}{" "}
                {t("Optimize plan", "تحسين الخطة")}
              </button>
            </div>
          </div>
          {help && (
            <div className="notice help">
              <div>
                <strong>
                  {t("The first useful loop", "دورة العمل الأساسية")}
                </strong>
                <p>
                  {t(
                    "Review the jobs and travel assumptions → optimize → compare against the greedy baseline → approve a rule or lock → optimize again. Use Data imports to review a CSV refresh. Costs are modeled in SAR. Every plan requires human review before any operational use.",
                    "راجع الشحنات وافتراضات السفر ← حسّن الخطة ← قارن بالمرجع ← اعتمد قاعدة أو تثبيتاً ← أعد التحسين. استخدم الاستيراد لمراجعة CSV. التكاليف تقديرية بالريال. تتطلب كل خطة مراجعة بشرية قبل أي استخدام تشغيلي.",
                  )}
                </p>
              </div>
              <button
                className="icon-button"
                aria-label={t("Close help", "إغلاق المساعدة")}
                onClick={() => setHelp(false)}
              >
                <X size={17} />
              </button>
            </div>
          )}
          {error && (
            <div className="notice bad row-between" role="alert">
              <span>{error}</span>
              <button
                className="icon-button"
                aria-label={t("Dismiss error", "إغلاق الخطأ")}
                onClick={() => setError("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {workspace.role === "viewer" && (
            <div className="notice">
              {t(
                "View-only access. A dispatcher can change inputs and run plans.",
                "صلاحية عرض فقط. يستطيع الموزّع تغيير المدخلات وتشغيل التخطيط.",
              )}
            </div>
          )}
          {activeRun && (
            <div className="notice progress">
              <LoaderCircle className="spin" size={18} />
              <div>
                <strong>
                  {activeRun.state === "queued"
                    ? t("Run queued", "الخطة في قائمة الانتظار")
                    : t(
                        "Building and checking your plan",
                        "جارٍ بناء الخطة والتحقق منها",
                      )}
                </strong>
                <p>
                  {t(
                    `Revision ${activeRun.revision} · attempt ${activeRun.attempt || 1}. Previous results remain available.`,
                    `النسخة ${activeRun.revision} · المحاولة ${activeRun.attempt || 1}. تبقى النتائج السابقة متاحة.`,
                  )}
                </p>
              </div>
              <button
                className="button"
                onClick={() =>
                  void act(async () => {
                    await send(`/api/runs/${activeRun.id}/cancel`, {});
                    setActiveRun(null);
                    await changed();
                  })
                }
              >
                {t("Cancel run", "إلغاء العملية")}
              </button>
            </div>
          )}
          {!!workspace.input_findings.length && (
            <div className="notice warn">
              <strong>
                {t("Inputs need attention", "المدخلات تحتاج مراجعة")}
              </strong>
              {workspace.input_findings.slice(0, 5).map((f, i) => (
                <p key={i}>{f.message}</p>
              ))}
            </div>
          )}
          {view === "planning" && (
            <div className="planning-layout">
              <div className="stack">
                <PlanningBoard
                  workspace={workspace}
                  run={selectedRun}
                  changed={changed}
                  act={act}
                  busy={busy || workspace.role === "viewer"}
                />
                {selectedRun?.result &&
                  (!selectedRun.result.candidate.valid ||
                    selectedRun.result.candidate.coverage === "partial") &&
                  !selectedRun.diagnostic && (
                    <div className="notice warn">
                      <div>
                        <strong>
                          {t(
                            "No complete validated plan returned",
                            "لم تُنتج خطة مكتملة صالحة",
                          )}
                        </strong>
                        <p>
                          {t(
                            "A diagnostic run can show the best coverage found, leaving unserved work explicit. It does not relax hard rules.",
                            "يمكن للتشخيص عرض أفضل تغطية عُثر عليها مع توضيح الأعمال غير المسندة، دون تخفيف القيود الإلزامية.",
                          )}
                        </p>
                      </div>
                      <button
                        className="button"
                        disabled={
                          busy || workspace.role === "viewer" || !!activeRun
                        }
                        onClick={() => void solve(true)}
                      >
                        {t("Run coverage diagnostic", "تشخيص التغطية")}
                      </button>
                    </div>
                  )}
              </div>
              <RulesPanel
                workspace={workspace}
                changed={changed}
                act={act}
                busy={busy || workspace.role === "viewer"}
              />
            </div>
          )}
          {view === "imports" && (
            <ImportPanel
              workspace={workspace}
              changed={changed}
              act={act}
              busy={busy || workspace.role === "viewer"}
            />
          )}
          {view === "rules" && (
            <div className="rules-page">
              <RulesPanel
                workspace={workspace}
                changed={changed}
                act={act}
                busy={busy || workspace.role === "viewer"}
              />
              <div className="panel padded">
                <ShieldCheck size={28} className="teal" />
                <h2>
                  {t(
                    "Rules become model constraints",
                    "تتحول القواعد إلى قيود للنموذج",
                  )}
                </h2>
                <p>
                  {t(
                    "Supported today: resource unavailability, final location deadlines, customer-only team eligibility, and required or preferred job assignments. Ambiguous or unsupported AI requests require clarification.",
                    "المدعوم حالياً: عدم توفر مورد، وموقع نهائي قبل موعد، وتخصيص فريق لعميل، وإسنادات إلزامية أو مفضلة. الطلبات الغامضة أو غير المدعومة تتطلب توضيحاً.",
                  )}
                </p>
                <div className="flow-step">
                  <span>1</span>
                  {t("Review an exact interpretation", "راجع التفسير المحدد")}
                </div>
                <div className="flow-step">
                  <span>2</span>
                  {t("Approve a versioned rule", "اعتمد نسخة من القاعدة")}
                </div>
                <div className="flow-step">
                  <span>3</span>
                  {t(
                    "Replan and independently validate",
                    "أعد التخطيط والتحقق المستقل",
                  )}
                </div>
                <div className="flow-step">
                  <span>4</span>
                  {t(
                    "Inspect coverage and cost effects",
                    "افحص التأثير على التغطية والتكلفة",
                  )}
                </div>
              </div>
            </div>
          )}
          {view === "history" && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>
                    {t("Every plan has a provenance", "لكل خطة سجل مدخلات")}
                  </h2>
                  <p>
                    {t(
                      "Saved inputs and results remain available after changes and restarts.",
                      "تبقى المدخلات والنتائج المحفوظة متاحة بعد التغييرات وإعادة التشغيل.",
                    )}
                  </p>
                </div>
                <History size={23} />
              </div>
              {!runs.length ? (
                <Empty
                  title={t(
                    "Your planning history starts here",
                    "يبدأ سجل التخطيط هنا",
                  )}
                >
                  {t(
                    "Run an optimization to save your first decision snapshot.",
                    "شغّل التحسين لحفظ أول لقطة للقرار.",
                  )}
                </Empty>
              ) : (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>{t("Created", "وقت الإنشاء")}</th>
                        <th>{t("Revision", "النسخة")}</th>
                        <th>{t("Mode", "الوضع")}</th>
                        <th>{t("Status", "الحالة")}</th>
                        <th>{t("Result", "النتيجة")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((run) => (
                        <tr key={run.id}>
                          <td>
                            {date(run.created_at)} {time(run.created_at)}
                            <div className="small subtle">
                              <code>{run.id.slice(0, 8)}</code>
                            </div>
                          </td>
                          <td>{run.revision}</td>
                          <td>
                            {run.diagnostic
                              ? t("Coverage diagnostic", "تشخيص التغطية")
                              : t(
                                  "All confirmed work required",
                                  "جميع الأعمال المؤكدة إلزامية",
                                )}
                          </td>
                          <td>
                            <Badge
                              tone={
                                run.state === "succeeded"
                                  ? "good"
                                  : run.state === "failed"
                                    ? "bad"
                                    : "neutral"
                              }
                            >
                              {run.state}
                            </Badge>
                          </td>
                          <td>
                            <button
                              className="text-button"
                              disabled={busy || run.state !== "succeeded"}
                              onClick={() =>
                                void act(async () => {
                                  setSelectedRun(
                                    await api<Run>(`/api/runs/${run.id}`),
                                  );
                                  setView("planning");
                                })
                              }
                            >
                              {t("Inspect plan", "فحص الخطة")}{" "}
                              <ArrowUpRight size={15} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}
          {view === "assumptions" && (
            <AssumptionsPanel
              key={workspace.version}
              workspace={workspace}
              changed={changed}
              act={act}
              busy={busy || workspace.role === "viewer"}
            />
          )}
          <footer className="app-footer">
            <span>
              <ShieldCheck size={13} />
              {workspace.snapshot.mode === "demo"
                ? t(
                    "Synthetic planning sandbox · no live publication",
                    "بيئة تخطيط تجريبية · لا يوجد نشر فعلي",
                  )
                : t(
                    "Plans for review · no dispatch publication",
                    "خطط للمراجعة · لا يوجد نشر لتعليمات التوزيع",
                  )}
            </span>
            <span>
              <CheckCheck size={13} />
              {t(
                "Python + CP-SAT · reviewed OpenAI rules",
                "Python + CP-SAT · قواعد OpenAI خاضعة للمراجعة",
              )}
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
