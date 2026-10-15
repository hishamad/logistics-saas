import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { Shell } from "./components/Shell";
import { I18nProvider, useI18n, type StringKey } from "./i18n";
import { Board } from "./pages/Board";
import { Data } from "./pages/Data";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";

function RequireLogin({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <div className="center">…</div>;
  return me ? <>{children}</> : <Navigate to="/login" replace />;
}

function ComingNext({ title, body }: { title: StringKey; body: StringKey }) {
  const { t } = useI18n();
  return (
    <div className="placeholder">
      <span className="badge">{t("comingSoon")}</span>
      <h1 style={{ marginTop: 10 }}>{t(title)}</h1>
      <p className="muted">{t(body)}</p>
    </div>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <RequireLogin>
                  <Shell />
                </RequireLogin>
              }
            >
              <Route index element={<Overview />} />
              <Route path="board" element={<Board />} />
              <Route path="data" element={<Data />} />
              <Route path="rules" element={<ComingNext title="navRules" body="comingRules" />} />
              <Route path="history" element={<ComingNext title="navHistory" body="comingHistory" />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </I18nProvider>
  );
}
