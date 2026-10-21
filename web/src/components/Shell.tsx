// The frame around every page: a slim rail of places, and a quiet top bar.
import { CalendarClock, Database, LayoutDashboard, LogOut, Moon, Route, Settings, SlidersHorizontal, Sun } from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { useTheme } from "../theme";

/** Madar means orbit: two paths around a centre. */
export function OrbitMark({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 34 34" aria-hidden="true">
      <ellipse cx="17" cy="17" rx="14" ry="6.5" fill="none" stroke="var(--accent)" strokeWidth="1.4" transform="rotate(-28 17 17)" />
      <ellipse cx="17" cy="17" rx="14" ry="6.5" fill="none" stroke="var(--muted)" strokeWidth="1" opacity=".55" transform="rotate(32 17 17)" />
      <circle cx="17" cy="17" r="3.2" fill="var(--text)" />
      <circle cx="29" cy="11" r="2" fill="var(--accent)" />
    </svg>
  );
}

export function Logo() {
  const { t } = useI18n();
  return (
    <div className="logo">
      <span className="logo-mark">
        <OrbitMark />
      </span>
      <span>
        MADAR <small>مدار</small>
        <br />
        <small>{t("tagline")}</small>
      </span>
    </div>
  );
}

/** Language and light/dark in one small switch. */
export function Preferences() {
  const { t, lang, toggle } = useI18n();
  const { theme, toggle: toggleTheme } = useTheme();
  return (
    <div className="seg" role="group" aria-label={t("preferences")}>
      <button type="button" aria-pressed={lang === "en"} onClick={() => lang !== "en" && toggle()}>
        EN
      </button>
      <button type="button" aria-pressed={lang === "ar"} onClick={() => lang !== "ar" && toggle()} lang="ar">
        ع
      </button>
      <span className="divider" aria-hidden="true" />
      <button type="button" onClick={toggleTheme} aria-label={t("themeSwitch")} title={t("themeSwitch")}>
        {theme === "night" ? <Sun size={15} aria-hidden /> : <Moon size={15} aria-hidden />}
      </button>
    </div>
  );
}

export function Shell() {
  const { t } = useI18n();
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const links = [
    { to: "/", label: t("navOverview"), icon: LayoutDashboard, end: true },
    { to: "/board", label: t("navBoard"), icon: Route },
    { to: "/data", label: t("navData"), icon: Database },
    { to: "/rules", label: t("navRules"), icon: SlidersHorizontal },
    { to: "/history", label: t("navHistory"), icon: CalendarClock },
    { to: "/settings", label: t("navSettings"), icon: Settings },
  ];
  return (
    <div className="shell">
      <nav className="rail" aria-label={t("workspace")}>
        <NavLink to="/" className="logo-mark" aria-label="Madar">
          <OrbitMark />
        </NavLink>
        {links.map(({ to, label, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => `rail-link${isActive ? " active" : ""}`} aria-label={label}>
            <Icon size={19} strokeWidth={1.6} aria-hidden />
            <span className="tip" aria-hidden="true">
              {label}
            </span>
          </NavLink>
        ))}
        <div className="rail-foot">
          {me && (
            <span className="avatar" title={`${me.user.name} · ${me.user.email}`} aria-hidden="true">
              {me.user.name.slice(0, 1).toUpperCase()}
            </span>
          )}
          <button
            type="button"
            className="rail-link"
            style={{ border: 0, background: "transparent" }}
            aria-label={t("signOut")}
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            <LogOut size={18} strokeWidth={1.6} aria-hidden />
            <span className="tip" aria-hidden="true">
              {t("signOut")}
            </span>
          </button>
        </div>
      </nav>
      <div className="content">
        <header className="topbar">
          {me && (
            <span className="who">
              <b>{me.company.name}</b> · {me.user.name} · {t(me.user.role)}
            </span>
          )}
          <Preferences />
        </header>
        <main className="main">
          {/* Keyed by path, so each page's parts arrive afresh. */}
          <div className="page" key={location.pathname}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
