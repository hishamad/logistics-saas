// While the engine plans: slow orbits, and the steps it is working through.
import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { useI18n } from "../i18n";

export function PlanOrbit({ startedAt, seconds, orders, trucks }: { startedAt: string; seconds: number; orders: number; trucks: number }) {
  const { t, fill, number } = useI18n();
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 400);
    return () => clearInterval(id);
  }, []);
  // The engine reports no progress; the steps follow the run's own time budget.
  const share = Math.max(0, (Date.now() - new Date(startedAt).getTime()) / 1000) / Math.max(1, seconds);
  const steps = [
    fill("stepReading", { n: number(orders) }),
    fill("stepPlacing", { n: number(trucks) }),
    t("stepHours"),
    t("stepCheck"),
  ];
  const reached = share < 0.08 ? 0 : share < 0.35 ? 1 : share < 0.85 ? 2 : 3;
  return (
    <div className="plan-orbit fade">
      <svg width="190" height="190" viewBox="0 0 240 240" aria-hidden="true">
        <circle cx="120" cy="120" r="70" fill="var(--accent-haze)" />
        <g className="orbit-b">
          <ellipse cx="120" cy="120" rx="108" ry="44" fill="none" stroke="var(--line-strong)" transform="rotate(32 120 120)" />
          <circle cx="214" cy="171" r="4" fill="var(--muted)" />
        </g>
        <g className="orbit-a">
          <ellipse cx="120" cy="120" rx="96" ry="38" fill="none" stroke="var(--accent)" strokeWidth="1.2" opacity=".7" transform="rotate(-28 120 120)" />
          <circle cx="205" cy="76" r="5" fill="var(--accent)" />
        </g>
        <g className="orbit-c">
          <circle cx="120" cy="120" r="54" fill="none" stroke="var(--accent)" strokeDasharray="2 9" opacity=".6" />
          <circle cx="174" cy="120" r="3" fill="var(--warm)" />
        </g>
        <circle cx="120" cy="120" r="12" fill="var(--text)" />
      </svg>
      <div className="plan-orbit-steps" role="status">
        <h2 className="breathe">{t("planningNow")}</h2>
        <ol>
          {steps.map((label, i) => (
            <li key={label} className={i < reached ? "done" : i === reached ? "now" : "todo"}>
              <span className="step-dot">{i < reached && <Check size={11} strokeWidth={3} aria-hidden />}</span>
              {label}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
