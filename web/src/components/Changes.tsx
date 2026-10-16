// What changed between two plans: counts first, details on demand.
import type { Changes } from "../api";
import { useI18n } from "../i18n";

export function ChangesView({ changes }: { changes: Changes }) {
  const { t, number, date } = useI18n();
  const time = (iso: string) => date(iso, { dateStyle: undefined, timeStyle: undefined, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const total = changes.moved.length + changes.retimed.length + changes.added.length + changes.dropped.length;
  if (total === 0) return <p className="empty">{t("chNothing")}</p>;
  return (
    <>
      <div className="change-counts">
        <Count n={changes.moved.length} label={t("chMoved")} strong />
        <Count n={changes.retimed.length} label={t("chRetimed")} />
        <Count n={changes.added.length} label={t("chAdded")} />
        <Count n={changes.dropped.length} label={t("chDropped")} strong />
        <Count n={changes.unchanged} label={t("chUnchanged")} />
        <Count n={changes.notify.length} label={t("chNotify")} strong />
      </div>
      <details className="change-details">
        <summary>{t("showDetails")}</summary>
        <ul>
          {changes.moved.map((c) => (
            <li key={`m${c.job}`}>
              <b>{c.ref}</b> <span className="muted">{c.customer}</span> · {c.from} → {c.to}
            </li>
          ))}
          {changes.dropped.map((c) => (
            <li key={`d${c.job}`} className="bad">
              <b>{c.ref}</b> <span className="muted">{c.customer}</span> · {t("chDropped")} ({c.truck})
            </li>
          ))}
          {changes.retimed.map((c) => (
            <li key={`r${c.job}`}>
              <b>{c.ref}</b> · {c.truck} · {t("pickupMoved")} {time(c.before)} → {time(c.after)}
            </li>
          ))}
          {changes.added.map((c) => (
            <li key={`a${c.job}`}>
              <b>{c.ref}</b> <span className="muted">{c.customer}</span> · {t("chAdded")} ({c.truck})
            </li>
          ))}
        </ul>
        {changes.notify.length > 0 && (
          <p className="small">
            <b>{t("chNotify")}:</b> {changes.notify.map((n) => `${n.truck} (${number(n.changes)})`).join(", ")}
          </p>
        )}
      </details>
    </>
  );
}

function Count({ n, label, strong }: { n: number; label: string; strong?: boolean }) {
  const { number } = useI18n();
  return (
    <div className={`count${strong && n > 0 ? " attention" : ""}`}>
      <b>{number(n)}</b>
      <span>{label}</span>
    </div>
  );
}
