// The selected truck, beside the timeline: its route, its orders in order, and what a
// dispatcher does with them (ask why, freeze, message the driver, ask "what if?").
import { useState } from "react";
import { api, type Board, type BoardTeam, type Lock } from "../api";
import { useI18n } from "../i18n";
import { Answer, useWhy } from "./Answer";
import type { DrawerTarget } from "./Drawer";
import { driverMessage } from "./driverMessage";
import { RouteMap } from "./RouteMap";
import { ACTIVITY_LABEL, useClock, useSites } from "./Timeline";

export function TruckCard({
  board,
  runId,
  team,
  locks,
  editable,
  onLocksChanged,
  onOpen,
}: {
  board: Board;
  runId: string;
  team: BoardTeam;
  locks: Lock[];
  editable: boolean;
  onLocksChanged: () => void;
  onOpen: (target: DrawerTarget) => void;
}) {
  const { t, fill, number, money, count } = useI18n();
  const site = useSites(board);
  const clock = useClock(board);
  const why = useWhy(runId);
  const [copied, setCopied] = useState<"" | "ok" | string>("");
  const [error, setError] = useState("");
  const arrow = <span className="arrow flip-rtl" aria-hidden="true">→</span>;

  // The truck's orders in the order it loads them.
  const jobs: { id: string; load?: number; unload?: number }[] = [];
  for (const act of team.acts) {
    const id = act[3];
    if (!id) continue;
    let job = jobs.find((j) => j.id === id);
    if (!job) jobs.push((job = { id }));
    if (act[8] === "loading") job.load = act[1];
    if (act[8] === "unloading") job.unload = act[1];
  }

  async function freeze(jobId: string, frozen: boolean) {
    setError("");
    try {
      if (frozen) await api.del(`/api/locks/${jobId}`);
      else await api.post("/api/locks", { job_id: jobId, team_id: team.id });
      onLocksChanged();
    } catch (caught) {
      setError((caught as Error).message);
    }
  }

  async function copy() {
    const words = { header: fill("msgHeader", { truck: team.name }), load: t("msgLoad"), unload: t("msgUnload"), none: t("msgNone") };
    const text = driverMessage(board, team, words, clock, site);
    try {
      await navigator.clipboard.writeText(text);
      setCopied("ok");
    } catch {
      setCopied(text); // no clipboard access: show the text to copy by hand
    }
  }

  const s = team.stats;
  return (
    <section className="truck-card panel slide-in" aria-label={t("selectedTruck")}>
      <header className="truck-head">
        <div>
          <h2>{team.name}</h2>
          <span className="muted small">
            {site(team.depot)} · {count("orders", s.jobs)}
          </span>
        </div>
        {s.jobs > 0 && <span className="truck-revenue">{money(s.revenue)}</span>}
      </header>
      {s.jobs > 0 && (
        <p className="muted small truck-line">
          {fill("drivingLine", { h: number(s.driving_h), loaded: number(s.loaded_km), empty: number(s.empty_km) })}
        </p>
      )}
      <RouteMap board={board} team={team} />
      {error && <div className="alert alert-error">{error}</div>}

      {jobs.length === 0 ? (
        <p className="muted truck-idle">{t("idlePanel")}</p>
      ) : (
        <ol className="truck-jobs">
          {jobs.map((item, i) => {
            const job = board.jobs[item.id];
            const frozen = locks.some((l) => l.job_id === item.id);
            return (
              <li key={item.id}>
                <span className="job-n">{number(i + 1)}</span>
                <div className="job-body">
                  <div className="job-top">
                    <span className="job-ref">
                      {job.ref}
                      {frozen && <span className="tag">{t("frozenBadge")}</span>}
                      {job.offer && <span className="tag warm">{t("spot")}</span>}
                    </span>
                    <span className="muted">{money(job.revenue)}</span>
                  </div>
                  <span className="muted">
                    {job.customer} · {job.tonnes} {t("tonnes")}
                  </span>
                  {item.load !== undefined && <span>{fill("atWhen", { what: t("msgLoad"), where: site(job.from), when: clock(item.load) })}</span>}
                  {item.unload !== undefined && <span>{fill("atWhen", { what: t("msgUnload"), where: site(job.to), when: clock(item.unload) })}</span>}
                  <div className="job-actions">
                    <button type="button" className="text-btn" onClick={() => void why.ask(item.id)} aria-expanded={why.answer?.job === item.id}>
                      {why.asking === item.id ? t("thinking") : t("why")} {arrow}
                    </button>
                    {editable && (
                      <button type="button" className="text-btn quiet" onClick={() => void freeze(item.id, frozen)}>
                        {frozen ? t("unfreeze") : job.offer ? t("freezeAccepts") : t("freezeOnTruck")}
                      </button>
                    )}
                    <button type="button" className="text-btn quiet" onClick={() => onOpen({ kind: "job", id: item.id })}>
                      {t("details")}
                    </button>
                  </div>
                  {why.answer?.job === item.id && <Answer text={why.answer.text} tone={why.answer.tone} />}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {team.acts.length > 0 && (
        <details className="every-step">
          <summary>{t("everyStep")}</summary>
          <ol>
            {team.acts.map((act, i) => (
              <li key={i}>
                <span className={`dot k-${["loaded", "empty", "handling", "waiting", "rest"][act[0]]}`} />
                <span className="step-when">{clock(act[1])}</span>
                <span>
                  {t(ACTIVITY_LABEL[act[8]])} · {act[4] === act[5] ? site(act[4]) : `${site(act[4])} → ${site(act[5])}`}
                  {act[6] ? ` · ${number(act[6])} ${t("colKm")}` : ""}
                </span>
              </li>
            ))}
          </ol>
        </details>
      )}

      <footer className="truck-foot">
        <button type="button" className="text-btn wide" onClick={() => void copy()}>
          {copied === "ok" ? t("msgCopiedShort") : t("msgCopy")}
          <span className="arrow" aria-hidden="true">{copied === "ok" ? "✓" : "⧉"}</span>
        </button>
        {copied && copied !== "ok" && <textarea className="input message-text" readOnly rows={8} value={copied} dir="auto" />}
        {editable && (
          <button type="button" className="text-btn wide" onClick={() => onOpen({ kind: "truck", id: team.id })}>
            {t("wiUnavailable")} {arrow}
          </button>
        )}
      </footer>
    </section>
  );
}
