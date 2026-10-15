import { Languages } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { Logo } from "../components/Shell";
import { useI18n } from "../i18n";

export function Login() {
  const { t, toggle } = useI18n();
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
      setError(caught instanceof ApiError && caught.status === 401 ? t("wrongLogin") : t("networkError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="login-brand">
        <Logo />
        <div>
          <h1>{t("loginTitle")}</h1>
          <p>{t("loginLead")}</p>
        </div>
        <button type="button" className="btn btn-ghost lang-switch" style={{ color: "#cfe2d9" }} onClick={toggle}>
          <Languages size={16} aria-hidden /> {t("language")}
        </button>
      </section>
      <section className="login-form">
        <form className="login-card" onSubmit={submit}>
          <h2>{t("signIn")}</h2>
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
          <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
            {busy ? t("signingIn") : t("signIn")}
          </button>
        </form>
      </section>
    </div>
  );
}
