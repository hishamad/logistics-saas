import { CalendarClock, Database, Languages, LayoutDashboard, LogOut, Route, SlidersHorizontal } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";

export function Logo() {
  const { t } = useI18n();
  return (
    <div className="logo">
      <span className="logo-mark" aria-hidden>
        <Route size={18} />
      </span>
      <span>
        MADAR <small>مدار</small>
        <br />
        <small>{t("tagline")}</small>
      </span>
    </div>
  );
}

export function Shell() {
  const { t, toggle } = useI18n();
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const links = [
    { to: "/", label: t("navOverview"), icon: LayoutDashboard, end: true },
    { to: "/board", label: t("navBoard"), icon: Route },
    { to: "/data", label: t("navData"), icon: Database },
    { to: "/rules", label: t("navRules"), icon: SlidersHorizontal },
    { to: "/history", label: t("navHistory"), icon: CalendarClock },
  ];
  return (
    <div className="shell">
      <aside className="sidebar">
        <Logo />
        {me && (
          <div className="company">
            <b>{me.company.name}</b>
            <span>{t(me.user.role)}</span>
          </div>
        )}
        <nav className="nav" aria-label={t("workspace")}>
          <div className="nav-label">{t("workspace")}</div>
          {links.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}>
              <Icon size={17} aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          {me && (
            <div className="user">
              <b>{me.user.name}</b>
              {me.user.email}
            </div>
          )}
          <button type="button" className="btn btn-ghost" onClick={toggle}>
            <Languages size={16} aria-hidden /> {t("language")}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            <LogOut size={16} aria-hidden /> {t("signOut")}
          </button>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
