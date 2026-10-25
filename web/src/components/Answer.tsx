// An answer from Madar: it streams in like a reply being written, then shows its actions.
import { useState, type ReactNode } from "react";
import { api, type WhyAnswer } from "../api";
import { useI18n } from "../i18n";
import { useStream } from "../motion";
import { OrbitMark } from "./Shell";

export function Answer({ title, text, tone = "", actions }: { title?: string; text: string; tone?: string; actions?: ReactNode }) {
  const { shown, done } = useStream(text);
  return (
    <div className={`answer-card rise ${tone}`} role="status">
      <OrbitMark size={22} />
      <div>
        {title && <div className="answer-title">{title}</div>}
        <p dir="auto">
          {shown}
          {!done && <span className="caret" aria-hidden="true" />}
        </p>
        {done && actions && <div className="result-actions fade">{actions}</div>}
      </div>
    </div>
  );
}

/** "Why is this order where it is?" for one order at a time, in the screen's language. */
export function useWhy(runId: string) {
  const { lang } = useI18n();
  const [answer, setAnswer] = useState<{ job: string; text: string; tone: string } | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  async function ask(job: string) {
    if (answer?.job === job) return setAnswer(null); // a second click puts it away
    setAsking(job);
    try {
      const why = await api.get<WhyAnswer>(`/api/plans/${runId}/why/${job}?lang=${lang}`);
      setAnswer({ job, text: why.text, tone: "" });
    } catch (caught) {
      setAnswer({ job, text: (caught as Error).message, tone: "error" });
    } finally {
      setAsking(null);
    }
  }
  return { answer, asking, ask, clear: () => setAnswer(null) };
}
