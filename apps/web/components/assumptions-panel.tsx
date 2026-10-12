"use client";

import { useState } from "react";
import { send, type Workspace } from "@/lib/api";
import { useLocale } from "@/lib/locale";
import { Badge } from "./ui";

export function AssumptionsPanel({
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
  const { t, time, date, num } = useLocale();
  const s = workspace.snapshot;
  const [distance, setDistance] = useState(
    s.costs.distance_minor_per_km == null
      ? ""
      : String(Number(s.costs.distance_minor_per_km) / 100),
  );
  const [duty, setDuty] = useState(
    s.costs.duty_minor_per_hour == null
      ? ""
      : String(Number(s.costs.duty_minor_per_hour) / 100),
  );
  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{t("Planning assumptions", "افتراضات التخطيط")}</h2>
            <p>
              {t(
                "Make the comparison meaningful before optimizing.",
                "تأكد من صلاحية افتراضات المقارنة قبل التحسين.",
              )}
            </p>
          </div>
          <Badge tone="warn">
            {s.mode === "demo"
              ? t("Synthetic estimates", "تقديرات تجريبية")
              : t("Review assumptions", "راجع الافتراضات")}
          </Badge>
        </div>
        <div className="padded">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                await send(
                  "/api/costs",
                  {
                    expected_version: workspace.version,
                    costs: {
                      ...s.costs,
                      distance_minor_per_km: distance.trim()
                        ? String(Math.round(Number(distance) * 10000) / 100)
                        : null,
                      duty_minor_per_hour: duty.trim()
                        ? String(Math.round(Number(duty) * 10000) / 100)
                        : null,
                    },
                  },
                  "PUT",
                );
                await changed();
              });
            }}
          >
            <div className="form-grid">
              <label>
                {t(
                  "Distance cost · SAR / km (includes fuel)",
                  "تكلفة المسافة · ريال / كم (تشمل الوقود)",
                )}
                <input
                  type="number"
                  min="0"
                  max="1000"
                  step="0.0001"
                  value={distance}
                  onChange={(e) => setDistance(e.target.value)}
                />
              </label>
              <label>
                {t("Duty cost · SAR / hour", "تكلفة التشغيل · ريال / ساعة")}
                <input
                  type="number"
                  min="0"
                  max="1000"
                  step="0.0001"
                  value={duty}
                  onChange={(e) => setDuty(e.target.value)}
                />
              </label>
            </div>
            <p className="subtle small">
              {t(
                "Leave a missing rate blank. A zero rate explicitly means no marginal cost for that component. Missing rates disable cash comparisons. Duty includes travel, service and waiting within each active route.",
                "اترك المعدّل فارغاً إذا لم يتوفر. يعني الصفر عدم وجود تكلفة هامشية لذلك البند. المعدّلات الناقصة تعطل المقارنة النقدية. يشمل وقت التشغيل السفر والخدمة والانتظار ضمن المسار.",
              )}
            </p>
            <div className="modal-actions">
              <button className="button primary" disabled={busy}>
                {t("Save cost assumptions", "حفظ افتراضات التكلفة")}
              </button>
            </div>
          </form>
          <div className="assumption-grid">
            <div>
              <span>{t("Decision horizon", "أفق القرار")}</span>
              <strong>
                {date(s.horizon.start)} {time(s.horizon.start)} →{" "}
                {date(s.horizon.end)} {time(s.horizon.end)}
              </strong>
            </div>
            <div>
              <span>{t("End-state policy", "سياسة نهاية المسار")}</span>
              <strong>
                {s.return_to_start
                  ? t(
                      "Return to start unless an approved rule overrides it",
                      "العودة للبداية ما لم تستبدلها قاعدة معتمدة",
                    )
                  : t(
                      "No default return; approved terminal rules still apply",
                      "لا توجد عودة افتراضية؛ تسري قواعد النهاية المعتمدة",
                    )}
              </strong>
            </div>
            <div>
              <span>{t("Cost exclusions", "استثناءات التكلفة")}</span>
              <strong>{s.costs.exclusions.join(" · ")}</strong>
            </div>
            <div>
              <span>{t("Planning precision", "دقة التخطيط")}</span>
              <strong>
                {t(
                  "Whole minutes · actual job windows checked afterwards",
                  "دقائق كاملة · يُتحقق من النوافذ الأصلية بعد الحل",
                )}
              </strong>
            </div>
          </div>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>{t("Resource readiness", "جاهزية الموارد")}</h2>
          <span className="subtle small">
            {t(
              "Refresh calendars through reviewed CSV",
              "حدّث التقويم من خلال CSV خاضع للمراجعة",
            )}
          </span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("Resource", "المورد")}</th>
                <th>{t("Location", "الموقع")}</th>
                <th>{t("Availability", "التوفر")}</th>
                <th>{t("Confirmed at", "وقت التأكيد")}</th>
                <th>{t("Capacity", "السعة")}</th>
              </tr>
            </thead>
            <tbody>
              {s.resources.map((r) => (
                <tr key={r.id}>
                  <td>
                    <strong>{r.name}</strong>
                    <div className="subtle small">{r.kind}</div>
                  </td>
                  <td>{r.site_id}</td>
                  <td>
                    {date(r.availability.start)} {time(r.availability.start)} →{" "}
                    {date(r.availability.end)} {time(r.availability.end)}
                  </td>
                  <td>
                    {date(r.confirmed_at)} {time(r.confirmed_at)}
                  </td>
                  <td>
                    {r.capacity_kg
                      ? `${num(r.capacity_kg / 1000)} ${t("tonnes", "طن")}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head">
          <h2>{t("Approved travel matrix", "مصفوفة تقديرات التنقل")}</h2>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t("From → to", "من ← إلى")}</th>
                <th>{t("Distance", "المسافة")}</th>
                <th>{t("Duration", "المدة")}</th>
                <th>{t("Source", "المصدر")}</th>
              </tr>
            </thead>
            <tbody>
              {s.lanes.map((l) => (
                <tr key={l.from_site_id + l.to_site_id}>
                  <td>
                    {l.from_site_id} → {l.to_site_id}
                  </td>
                  <td>{num(l.distance_m / 1000)} km</td>
                  <td>{l.duration_minutes} min</td>
                  <td className="subtle small">{l.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
