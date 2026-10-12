"use client";

import { useEffect, useRef, useState } from "react";
import { Download, FileUp, CheckCheck } from "lucide-react";
import {
  api,
  apiBase,
  send,
  type ImportBatch,
  type Workspace,
} from "@/lib/api";
import { useLocale } from "@/lib/locale";
import { Badge } from "./ui";

const columns: Record<string, string[]> = {
  jobs: [
    "id",
    "reference",
    "customer",
    "pickup_site_id",
    "delivery_site_id",
    "pickup_start",
    "pickup_end",
    "delivery_start",
    "delivery_end",
    "delivery_window_kind",
    "equipment",
    "weight_kg",
    "priority",
    "state",
    "loading_minutes",
    "unloading_minutes",
    "turnaround_minutes",
    "revenue_minor",
  ],
  resources: [
    "id",
    "name",
    "kind",
    "site_id",
    "available_start",
    "available_end",
    "confirmed_at",
    "equipment",
    "capacity_kg",
  ],
  lanes: [
    "from_site_id",
    "to_site_id",
    "distance_m",
    "duration_minutes",
    "source",
  ],
};

// Read one CSV header record, including quoted commas, newlines and escaped quotes.
function csvHeaders(text: string) {
  const fields: string[] = [];
  let field = "",
    quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      if (quoted && text[i + 1] === '"') {
        field += '"';
        i++;
      } else quoted = !quoted;
    } else if (c === "," && !quoted) {
      fields.push(field);
      field = "";
    } else if ((c === "\n" || c === "\r") && !quoted) break;
    else field += c;
  }
  fields.push(field);
  return fields;
}

export function ImportPanel({
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
  const [entity, setEntity] = useState("jobs");
  const [content, setContent] = useState("");
  const [name, setName] = useState("CSV import");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [overrides, setOverrides] = useState<number[]>([]);
  const [message, setMessage] = useState("");
  const commitIdentity = useRef({ signature: "", key: "" });
  const [profiles, setProfiles] = useState<
    { name: string; entity: string; mapping: Record<string, string> }[]
  >([]);
  useEffect(() => {
    void api<typeof profiles>("/api/mapping-profiles")
      .then(setProfiles)
      .catch(() => {});
  }, []);
  const commitKey = () => {
    const signature = JSON.stringify({
      batch: batch?.id,
      selected: [...selected].sort(),
      overrides: overrides.filter((line) => selected.includes(line)).sort(),
    });
    if (commitIdentity.current.signature !== signature)
      commitIdentity.current = { signature, key: crypto.randomUUID() };
    return commitIdentity.current.key;
  };
  const headers = content ? csvHeaders(content.replace(/^\uFEFF/, "")) : [];
  const invalidate = () => {
    setBatch(null);
    setMessage("");
    setOverrides([]);
  };
  return (
    <section className="panel import-panel">
      <div className="panel-head">
        <div>
          <h2>{t("Bring your planning data", "أضف بيانات التخطيط")}</h2>
          <p>
            {t(
              "Map columns, review changes, then commit an exact revision.",
              "طابق الأعمدة، راجع التغييرات، ثم احفظ نسخة محددة.",
            )}
          </p>
        </div>
        <FileUp size={24} />
      </div>
      <div className="padded">
        <div className="notice">
          {t(
            "Import only data approved for this workspace. Times need an explicit offset, such as 2026-10-12T08:00:00+03:00. Distances are metres, weights kg, prices halalas. Stable IDs identify updates; omitted rows are not deleted.",
            "استورد البيانات المعتمدة لهذه المساحة فقط. يجب تحديد فرق التوقيت. المسافات بالأمتار والأوزان بالكيلوغرام والأسعار بالهللات. تعرّف المعرّفات الثابتة التحديثات ولا تُحذف الصفوف الغائبة.",
          )}
        </div>
        <div className="form-grid">
          <label>
            {t("Data to import", "نوع البيانات")}
            <select
              value={entity}
              onChange={(e) => {
                setEntity(e.target.value);
                setMapping({});
                invalidate();
              }}
            >
              <option value="jobs">{t("Jobs", "الشحنات")}</option>
              <option value="resources">{t("Resources", "الموارد")}</option>
              <option value="lanes">
                {t("Travel estimates", "تقديرات الرحلات")}
              </option>
            </select>
          </label>
          <label>
            {t("Source profile name", "اسم ملف المصدر")}
            <input
              maxLength={150}
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                invalidate();
              }}
            />
          </label>
        </div>
        <div className="upload-zone">
          <FileUp size={30} />
          <h3>{t("Choose a CSV file", "اختر ملف CSV")}</h3>
          <p>
            {t(
              "Up to 2 MB · 500 rows · UTF-8",
              "حتى ٢ ميغابايت · ٥٠٠ صف · UTF-8",
            )}
          </p>
          <input
            aria-label={t("CSV file", "ملف CSV")}
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file)
                void act(async () => {
                  if (file.size > 2_000_000)
                    throw new Error(
                      t("CSV limit is 2 MB", "الحد الأقصى ٢ ميغابايت"),
                    );
                  const value = await file.text();
                  setContent(value);
                  setName(file.name);
                  setMapping({});
                  invalidate();
                });
            }}
          />
          <a
            className="text-button"
            href={apiBase() + `/api/templates/${entity}`}
          >
            <Download size={14} />
            {t("Download current input template", "تنزيل قالب المدخلات الحالي")}
          </a>
        </div>
        <details>
          <summary>{t("Or paste CSV", "أو الصق CSV")}</summary>
          <textarea
            className="code-input"
            dir="ltr"
            aria-label="CSV contents"
            rows={6}
            maxLength={2000000}
            value={content}
            onChange={(e) => {
              setContent(e.target.value);
              invalidate();
            }}
          />
        </details>
        {!!headers.length && (
          <details className="mapping">
            <summary>
              {t("Column mapping", "مطابقة الأعمدة")} · {headers.length}{" "}
              {t("source columns", "أعمدة المصدر")}
            </summary>
            {profiles.some((p) => p.entity === entity) && (
              <label>
                {t("Reuse a saved mapping", "إعادة استخدام مطابقة محفوظة")}
                <select
                  defaultValue=""
                  onChange={(e) => {
                    const profile = profiles.find(
                      (p) => p.name === e.target.value,
                    );
                    if (profile) {
                      setMapping(
                        Object.fromEntries(
                          columns[entity].map((field) => [
                            field,
                            profile.mapping[field] ?? "",
                          ]),
                        ),
                      );
                      setName(profile.name);
                      invalidate();
                    }
                  }}
                >
                  <option value="">
                    {t("Choose a source profile", "اختر ملف مصدر")}
                  </option>
                  {profiles
                    .filter((p) => p.entity === entity)
                    .map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                      </option>
                    ))}
                </select>
              </label>
            )}
            <div className="form-grid">
              {columns[entity].map((field) => (
                <label key={field}>
                  {field}
                  <select
                    value={
                      mapping[field] ?? (headers.includes(field) ? field : "")
                    }
                    onChange={(e) => {
                      setMapping({ ...mapping, [field]: e.target.value });
                      invalidate();
                    }}
                  >
                    <option value="">
                      {t(
                        "Keep existing / default for new rows",
                        "حفظ القيمة الحالية / الافتراضية للصفوف الجديدة",
                      )}
                    </option>
                    {headers.map((h, i) => (
                      <option value={h} key={`${h}-${i}`}>
                        {h}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          </details>
        )}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !content || !name.trim()}
            onClick={() =>
              void act(async () => {
                const resolved = Object.fromEntries(
                  columns[entity]
                    .map((f) => [
                      f,
                      mapping[f] ?? (headers.includes(f) ? f : ""),
                    ])
                    .filter(([, v]) => v),
                );
                const value = await send<ImportBatch>("/api/imports", {
                  entity,
                  content,
                  source_name: name,
                  mapping: resolved,
                });
                setBatch(value);
                setSelected(
                  value.rows
                    .filter(
                      (r) => r.status !== "invalid" && r.status !== "conflict",
                    )
                    .map((r) => r.line),
                );
                setOverrides([]);
                setMessage("");
              })
            }
          >
            {t("Preview & validate", "معاينة والتحقق")}
          </button>
        </div>
        {message && (
          <div className="notice good">
            <CheckCheck size={17} />
            {message}
          </div>
        )}
        {batch && (
          <>
            <div className="row-between">
              <h3>{t("Review changes", "مراجعة التغييرات")}</h3>
              <Badge>
                {t("Revision", "النسخة")} {batch.base_version}
              </Badge>
            </div>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t("Accept", "قبول")}</th>
                    <th>{t("Row / ID", "الصف / المعرّف")}</th>
                    <th>{t("Change", "التغيير")}</th>
                    <th>{t("Review", "المراجعة")}</th>
                  </tr>
                </thead>
                <tbody>
                  {batch.rows.map((row) => (
                    <tr key={row.line}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`${t("Accept row", "قبول الصف")} ${row.line}`}
                          disabled={row.status === "invalid"}
                          checked={selected.includes(row.line)}
                          onChange={(e) =>
                            setSelected(
                              e.target.checked
                                ? [...selected, row.line]
                                : selected.filter((v) => v !== row.line),
                            )
                          }
                        />
                      </td>
                      <td>
                        {row.line} <code>{row.external_id}</code>
                      </td>
                      <td>
                        <Badge
                          tone={
                            row.status === "invalid"
                              ? "bad"
                              : row.status === "conflict"
                                ? "warn"
                                : row.status === "new"
                                  ? "good"
                                  : "neutral"
                          }
                        >
                          {row.status}
                        </Badge>
                      </td>
                      <td>
                        {row.errors.map((err, i) => (
                          <p className="small error-text" key={i}>
                            {err}
                          </p>
                        ))}
                        {row.status === "conflict" && (
                          <label className="check">
                            <input
                              type="checkbox"
                              checked={overrides.includes(row.line)}
                              onChange={(e) =>
                                setOverrides(
                                  e.target.checked
                                    ? [...overrides, row.line]
                                    : overrides.filter((v) => v !== row.line),
                                )
                              }
                            />
                            {t(
                              "Replace current values after review",
                              "استبدال القيم الحالية بعد المراجعة",
                            )}
                          </label>
                        )}
                        {row.data && (
                          <details>
                            <summary>
                              {t("Inspect fields", "فحص الحقول")}
                            </summary>
                            <div className="diff-grid">
                              {Object.entries(row.data)
                                .filter(
                                  ([k, v]) =>
                                    !row.previous ||
                                    JSON.stringify(row.previous[k]) !==
                                      JSON.stringify(v),
                                )
                                .map(([k, v]) => (
                                  <div key={k}>
                                    <strong>{k}</strong>
                                    {row.previous && (
                                      <del>
                                        {JSON.stringify(row.previous[k])}
                                      </del>
                                    )}
                                    <span>
                                      {typeof v === "object"
                                        ? JSON.stringify(v)
                                        : String(v)}
                                    </span>
                                  </div>
                                ))}
                            </div>
                          </details>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="modal-actions">
              <span className="subtle">
                {selected.length} {t("selected", "محدد")}
              </span>
              <button
                className="button primary"
                disabled={
                  busy ||
                  !selected.length ||
                  batch.base_version !== workspace.version ||
                  batch.rows.some(
                    (r) =>
                      selected.includes(r.line) &&
                      r.status === "conflict" &&
                      !overrides.includes(r.line),
                  )
                }
                onClick={() =>
                  void act(async () => {
                    const result = await send<{
                      changed: number;
                      version: number;
                    }>(`/api/imports/${batch.id}/commit`, {
                      expected_version: batch.base_version,
                      lines: selected,
                      overrides: overrides.filter((line) =>
                        selected.includes(line),
                      ),
                      idempotency_key: commitKey(),
                    });
                    setMessage(
                      t(
                        `Committed ${result.changed} changes. Current revision: ${result.version}.`,
                        `تم حفظ ${result.changed} تغييرات. النسخة الحالية: ${result.version}.`,
                      ),
                    );
                    setBatch(null);
                    await changed();
                  })
                }
              >
                {t("Commit reviewed rows", "حفظ الصفوف المراجعة")}
              </button>
            </div>
            {batch.base_version !== workspace.version && (
              <p className="error-text">
                {t(
                  "Inputs changed. Preview the file again.",
                  "تغيرت المدخلات. أعد معاينة الملف.",
                )}
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}
