import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { Logo, Preferences } from "../components/Shell";
import { useI18n } from "../i18n";

/** Large, slow orbits behind the welcome text. */
function Orbits() {
  return (
    <svg className="login-orbit" viewBox="0 0 620 620" aria-hidden="true">
      <g style={{ transformOrigin: "310px 310px", animation: "spin-back 60s linear infinite" }}>
        <ellipse cx="310" cy="310" rx="290" ry="118" fill="none" stroke="var(--line-strong)" transform="rotate(32 310 310)" />
        <circle cx="556" cy="458" r="5" fill="var(--muted)" />
      </g>
      <g style={{ transformOrigin: "310px 310px", animation: "spin 40s linear infinite" }}>
        <ellipse cx="310" cy="310" rx="250" ry="100" fill="none" stroke="var(--accent)" strokeOpacity=".55" transform="rotate(-28 310 310)" />
        <circle cx="530" cy="196" r="6" fill="var(--accent)" />
      </g>
      <circle cx="310" cy="310" r="120" fill="var(--accent-haze)" />
      <circle cx="310" cy="310" r="16" fill="var(--text)" />
    </svg>
  );
}

export function Login() {
  const { t } = useI18n();
  const { me, login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (me) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email, password);
      navigate("/");
    } catch (caught) {
      const status = caught instanceof ApiError ? caught.status : 0;
      setError(status === 401 ? t("wrongLogin") : status === 429 ? t("tooManyLogins") : t("networkError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="login-brand">
        <Orbits />
        <Logo />
        <div className="rise">
          <h1>{t("loginTitle")}</h1>
          <p>{t("loginLead")}</p>
        </div>
        <div className="lang-switch">
          <Preferences />
        </div>
      </section>
      <section className="login-form">
        <form className="login-card rise" onSubmit={submit} style={{ animationDelay: "120ms" }}>
          <h2 style={{ fontSize: 20, fontWeight: 300 }}>{t("signIn")}</h2>
          {error && (
            <div className="alert alert-error" role="alert">
              {error}
            </div>
          )}
          <div className="field">
            <label htmlFor="email">{t("email")}</label>
            <input
              id="email"
              className="input"
              type="email"
              autoComplete="username"
              required
              dir="ltr"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">{t("password")}</label>
            <input
              id="password"
              className="input"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn-primary" style={{ width: "100%", minHeight: 46 }} disabled={busy}>
            {busy ? t("signingIn") : t("signIn")}
          </button>
        </form>
      </section>
    </div>
  );
}
