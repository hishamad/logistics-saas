// "Ask Madar": a question about an order gets the plan's own explanation; anything else is
// read as an instruction and proposed as a rule, which the dispatcher must add themselves.
import { useRef, useState, type FormEvent } from "react";
import { api, type Interpretation, type Rule, type Steering, type WhyAnswer } from "../api";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { Answer } from "./Answer";
import { OrbitMark } from "./Shell";

type Answer = { kind: "why" | "rule" | "note" | "error"; title: string; text: string; rule?: Rule };

const REFERENCE = /\b[A-Za-z]{2,6}-\d{3,}\b/;

export function AskBar({ runId, suggestions }: { runId: string | null; suggestions: string[] }) {
  const { t, fill, lang } = useI18n();
  const { canPlan } = useAuth();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const jobs = useRef<Steering["jobs"] | null>(null);

  async function ask(question: string) {
    const q = question.trim();
    if (!q) return;
    setText(q);
    setBusy(true);
    setAnswer(null);
    try {
      // Truck names look like order references too (DMM-034), so only a known order is a "why".
      const ref = q.match(REFERENCE)?.[0];
      if (ref) {
        jobs.current ??= (await api.get<Steering>("/api/steering")).jobs;
        const job = jobs.current.find((j) => j.reference.toLowerCase() === ref.toLowerCase());
        if (job) {
          if (!runId) return setAnswer({ kind: "note", title: t("askMadar"), text: t("noPlanForWhy") });
          const why = await api.get<WhyAnswer>(`/api/plans/${runId}/why/${job.id}?lang=${lang}`);
          return setAnswer({ kind: "why", title: fill("answerWhy", { ref: job.reference }), text: why.text });
        }
        if (!canPlan) return setAnswer({ kind: "note", title: t("askMadar"), text: fill("unknownRef", { ref }) });
      }
      if (!canPlan) return setAnswer({ kind: "note", title: t("askMadar"), text: t("viewerRulesNote") });
      const reply = await api.post<Interpretation>("/api/rules/interpret", { text: q, lang });
      if (reply.status === "proposed" && reply.rule) {
        return setAnswer({ kind: "rule", title: t("proposal"), text: reply.explanation, rule: reply.rule });
      }
      setAnswer({ kind: reply.status === "error" ? "error" : "note", title: t("answerUnclear"), text: reply.question || reply.explanation });
    } catch (caught) {
      setAnswer({ kind: "error", title: t("answerUnclear"), text: (caught as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function addRule(rule: Rule) {
    const { id: _, ...body } = rule;
    try {
      await api.post("/api/rules", body);
      setAnswer({ kind: "note", title: t("proposal"), text: t("ruleAdded") });
      setText("");
    } catch (caught) {
      setAnswer({ kind: "error", title: t("answerUnclear"), text: (caught as Error).message });
    }
  }

  return (
    <section className="ask-madar" aria-label={t("askMadar")}>
      <form
        className="ask-bar"
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          void ask(text);
        }}
      >
        <span className={busy ? "breathe" : undefined} style={{ display: "grid" }}>
          <OrbitMark size={24} />
        </span>
        <label htmlFor="ask-madar" className="visually-hidden">
          {t("askMadar")}
        </label>
        <input id="ask-madar" value={text} onChange={(e) => setText(e.target.value)} placeholder={t("askPlaceholder2")} autoComplete="off" dir="auto" />
        <button type="submit" className="kbd-btn" aria-label={t("send")} disabled={busy}>
          <span className="kbd">
            {t("enterKey")} <span aria-hidden="true">↵</span>
          </span>
        </button>
      </form>
      {suggestions.length > 0 && (
        <div className="ask-try">
          <span>{t("tryLabel")}</span>
          {suggestions.map((s) => (
            <button key={s} type="button" className="suggest" onClick={() => void ask(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      {busy && <p className="muted small breathe">{t("thinking")}</p>}
      {answer && (
        <Answer
          title={answer.title}
          text={answer.text}
          tone={answer.kind}
          actions={
            <>
              {answer.kind === "rule" && answer.rule && (
                <button type="button" className="btn btn-primary" onClick={() => void addRule(answer.rule!)}>
                  {t("addThisRule")}
                </button>
              )}
              <button type="button" className="text-btn" style={{ color: "var(--muted)" }} onClick={() => setAnswer(null)}>
                {answer.kind === "rule" ? t("discard") : t("close")}
              </button>
            </>
          }
        />
      )}
    </section>
  );
}
