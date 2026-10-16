// Data in: the planning window, orders and fleet as Excel/CSV, and the site list.
// Uploads are checked first; nothing changes until the dispatcher applies.
import { CalendarRange, Download, FileSpreadsheet, MapPin, Truck, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, type DataOverview, type SheetKind, type SheetProblem, type UploadResult } from "../api";
import { useAuth } from "../auth";
import { useI18n, type StringKey } from "../i18n";
import { fromRiyadhInput, toRiyadhInput } from "../time";


export function Data() {
  const { t, number, date } = useI18n();
  const { me } = useAuth();
  const [data, setData] = useState<DataOverview | null>(null);
  const [error, setError] = useState("");
  const editable = me?.user.role === "dispatcher";

  const load = useCallback(() => {
    api
      .get<DataOverview>("/api/data")
      .then(setData)
      .catch((caught: Error) => setError(caught.message));
  }, []);
  useEffect(load, [load]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("dataTitle")}</h1>
          <span className="muted">{t("dataLead")}</span>
        </div>
        {data && (
          <span className="muted">
            {t("dataVersion")} {number(data.version)} · {date(data.updated_at)}
          </span>
        )}
      </div>
      {error && <div className="alert alert-error">{error}</div>}
      {!editable && <div className="alert alert-info">{t("viewerCannotEdit")}</div>}
      {data && (
        <div className="data-grid">
          <WindowCard data={data} editable={editable} onChanged={load} />
          <SheetCard kind="jobs" data={data} editable={editable} onChanged={load} />
          <SheetCard kind="fleet" data={data} editable={editable} onChanged={load} />
          <SitesCard data={data} />
        </div>
      )}
    </>
  );
}

function WindowCard({ data, editable, onChanged }: { data: DataOverview; editable: boolean; onChanged: () => void }) {
  const { t, number } = useI18n();
  const days = Math.round((new Date(data.window.end).getTime() - new Date(data.window.start).getTime()) / 86400000);
  const [start, setStart] = useState(toRiyadhInput(data.window.start));
  const [length, setLength] = useState(days);
  const [state, setState] = useState<"idle" | "saving" | "saved" | string>("idle");
  const changed = start !== toRiyadhInput(data.window.start) || length !== days;

  async function save() {
    setState("saving");
    try {
      await api.post("/api/data/window", { start: fromRiyadhInput(start), days: length });
      setState("saved");
      onChanged();
    } catch (caught) {
      setState((caught as Error).message);
    }
  }

  return (
    <section className="panel data-window">
      <h2>
        <CalendarRange size={18} aria-hidden /> {t("windowTitle")}
      </h2>
      <div className="window-form">
        <label className="field">
          <span>{t("windowStart")}</span>
          <input className="input" type="datetime-local" value={start} disabled={!editable} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="field">
          <span>{t("windowDays")}</span>
          <select className="input" value={length} disabled={!editable} onChange={(e) => setLength(Number(e.target.value))}>
            {[1, 2, 3, 4, 5, 6, 7].map((d) => (
              <option key={d} value={d}>
                {number(d)} {t("days")}
              </option>
            ))}
          </select>
        </label>
        {editable && (
          <button className="btn btn-primary" onClick={save} disabled={!changed || !start || state === "saving"}>
            {t("save")}
          </button>
        )}
        {state === "saved" && !changed && <span className="ok-text">{t("saved")}</span>}
        {state !== "idle" && state !== "saving" && state !== "saved" && <span className="error-text">{state}</span>}
      </div>
      {data.jobs.outside_window > 0 && (
        <div className="alert alert-warn">
          {number(data.jobs.outside_window)} {t("outsideWindow")}
        </div>
      )}
    </section>
  );
}

type Phase =
  | { step: "idle" }
  | { step: "checking"; file: File }
  | { step: "checked"; file: File; result: UploadResult }
  | { step: "applying"; file: File; result: UploadResult }
  | { step: "applied"; result: UploadResult }
  | { step: "failed"; message: string };

function SheetCard({ kind, data, editable, onChanged }: { kind: SheetKind; data: DataOverview; editable: boolean; onChanged: () => void }) {
  const { t, number } = useI18n();
  const [phase, setPhase] = useState<Phase>({ step: "idle" });
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const jobs = kind === "jobs";

  async function check(file: File) {
    setPhase({ step: "checking", file });
    try {
      const result = await api.upload<UploadResult>(`/api/data/${kind}`, file);
      setPhase({ step: "checked", file, result });
    } catch (caught) {
      setPhase({ step: "failed", message: (caught as Error).message });
    }
  }

  async function apply(file: File, result: UploadResult) {
    setPhase({ step: "applying", file, result });
    try {
      const applied = await api.upload<UploadResult>(`/api/data/${kind}?apply=true&version=${result.version}`, file);
      setPhase(applied.applied ? { step: "applied", result: applied } : { step: "checked", file, result: applied });
      if (applied.applied) onChanged();
    } catch (caught) {
      const message = caught instanceof ApiError && caught.status === 409 ? t("conflict") : (caught as Error).message;
      setPhase({ step: "failed", message });
    }
  }

  function pick(files: FileList | null) {
    const file = files?.[0];
    if (file) void check(file);
    if (input.current) input.current.value = "";
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (editable) pick(event.dataTransfer.files);
  }

  const busy = phase.step === "checking" || phase.step === "applying";
  return (
    <section className="panel">
      <h2>
        {jobs ? <FileSpreadsheet size={18} aria-hidden /> : <Truck size={18} aria-hidden />} {t(jobs ? "ordersTitle" : "fleetTitle")}
      </h2>
      <p className="muted">{t(jobs ? "ordersLead" : "fleetLead")}</p>
      <div className="counts">
        {jobs ? (
          <>
            <Count value={number(data.jobs.contract)} label={t("contractCount")} />
            <Count value={number(data.jobs.spot)} label={t("spotCount")} />
            <Count value={number(data.jobs.customers)} label={t("customers")} />
          </>
        ) : (
          <>
            <Count value={number(data.fleet.trucks)} label={t("trucksCount")} />
            <Count value={number(data.fleet.dry_van)} label={t("dryVan")} />
            <Count value={number(data.fleet.flatbed)} label={t("flatbed")} />
          </>
        )}
      </div>
      <div className="downloads">
        <a className="btn" href={`/api/data/${kind}.xlsx`} download>
          <Download size={16} aria-hidden /> {t("downloadCurrent")}
        </a>
        <a className="btn btn-ghost" href={`/api/data/${kind}.xlsx?template=true`} download>
          {t("downloadTemplate")}
        </a>
      </div>
      {editable && (
        <div
          className={`dropzone${dragging ? " over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
        >
          <button className="btn btn-primary" onClick={() => input.current?.click()} disabled={busy}>
            <Upload size={16} aria-hidden /> {t("chooseFile")}
          </button>
          <span className="muted">{t("dropHint")}</span>
          <input ref={input} type="file" accept=".xlsx,.csv" hidden onChange={(e) => pick(e.target.files)} />
        </div>
      )}
      <Result kind={kind} phase={phase} onApply={apply} onCancel={() => setPhase({ step: "idle" })} />
    </section>
  );
}

function Count({ value, label }: { value: string; label: string }) {
  return (
    <div className="count">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}

function Result({
  kind,
  phase,
  onApply,
  onCancel,
}: {
  kind: SheetKind;
  phase: Phase;
  onApply: (file: File, result: UploadResult) => void;
  onCancel: () => void;
}) {
  const { t, number } = useI18n();
  if (phase.step === "idle") return null;
  if (phase.step === "checking") return <p className="result muted">{t("checking")}</p>;
  if (phase.step === "failed") return <div className="alert alert-error result">{phase.message}</div>;
  if (phase.step === "applied") {
    return (
      <div className="alert alert-ok result">
        {t("appliedNote")} <Link to="/board">{t("openBoard")}</Link>
      </div>
    );
  }
  const { file, result } = phase;
  if (result.file_error) {
    const key = `f_${result.file_error}` as StringKey;
    return (
      <div className="alert alert-error result">
        <bdi className="file-name">{file.name}</bdi>: {t(key)} {result.detail}
      </div>
    );
  }
  const s = result.summary;
  if (result.problems.length > 0) {
    const total = result.problem_count ?? result.problems.length;
    return (
      <div className="result">
        <div className="alert alert-error">
          <bdi className="file-name">{file.name}</bdi>: {number(total)} {t("problemsFound")} {total > result.problems.length && t("moreProblems")}
        </div>
        <Problems problems={result.problems} />
      </div>
    );
  }
  const parts: ReactNode[] = [`${number(s.rows)} ${t("sumRows")}`];
  if (kind === "jobs") parts.push(`${number(s.contract)} ${t("contractCount")}`, `${number(s.spot)} ${t("spotCount")}`);
  parts.push(`${number(s.added)} ${t("sumAdded")}`, `${number(s.removed)} ${t("sumRemoved")}`, `${number(s.kept)} ${t("sumKept")}`);
  return (
    <div className="result">
      <div className="alert alert-ok">
        <bdi className="file-name">{file.name}</bdi>: {t("checkedOk")}
        <div>{parts.join(" · ")}</div>
        {s.outside_window > 0 && (
          <div>
            {number(s.outside_window)} {t("outsideWindow")}
          </div>
        )}
        {s.locks_dropped > 0 && (
          <div>
            {number(s.locks_dropped)} {t("sumLocks")}
          </div>
        )}
        {s.rules_dropped > 0 && (
          <div>
            {number(s.rules_dropped)} {t("sumRules")}
          </div>
        )}
      </div>
      <div className="result-actions">
        <button className="btn btn-primary" onClick={() => onApply(file, result)} disabled={phase.step === "applying"}>
          {phase.step === "applying" ? t("applying") : t("apply")}
        </button>
        <button className="btn" onClick={onCancel} disabled={phase.step === "applying"}>
          {t("cancel")}
        </button>
      </div>
    </div>
  );
}

function Problems({ problems }: { problems: SheetProblem[] }) {
  const { t, number } = useI18n();
  const describe = (p: SheetProblem) => {
    const label = t(`p_${p.code}` as StringKey) ?? p.code;
    if (p.code === "duplicate") return `${label} ${p.detail})`;
    return p.detail ? `${label} (${p.detail})` : label;
  };
  return (
    <div className="table-wrap problems">
      <table>
        <thead>
          <tr>
            <th className="num">{t("colRow")}</th>
            <th>{t("colColumn")}</th>
            <th>{t("colProblem")}</th>
            <th>{t("colValue")}</th>
          </tr>
        </thead>
        <tbody>
          {problems.map((p, i) => (
            <tr key={i}>
              <td className="num">{p.row ? number(p.row) : "—"}</td>
              <td>
                <code>{p.column}</code>
              </td>
              <td>{describe(p)}</td>
              <td className="value-cell" dir="auto">{p.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SitesCard({ data }: { data: DataOverview }) {
  const { t } = useI18n();
  return (
    <section className="panel data-sites">
      <h2>
        <MapPin size={18} aria-hidden /> {t("sitesTitle")}
      </h2>
      <p className="muted">{t("sitesLead")}</p>
      <div className="table-wrap sites-table">
        <table>
          <thead>
            <tr>
              <th>{t("siteId")}</th>
              <th>{t("siteName")}</th>
              <th>{t("siteNameAr")}</th>
            </tr>
          </thead>
          <tbody>
            {data.sites.map((site) => (
              <tr key={site.id}>
                <td>
                  <code>{site.id}</code>
                </td>
                <td>{site.name}</td>
                <td dir="rtl">{site.name_ar}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
