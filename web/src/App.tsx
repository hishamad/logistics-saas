import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { Shell } from "./components/Shell";
import { I18nProvider } from "./i18n";
import { Board } from "./pages/Board";
import { Data } from "./pages/Data";
import { History } from "./pages/History";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { Rules } from "./pages/Rules";
import { Settings } from "./pages/Settings";

function RequireLogin({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  if (loading) return <div className="center">…</div>;
  return me ? <>{children}</> : <Navigate to="/login" replace />;
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
              <Route path="rules" element={<Rules />} />
              <Route path="history" element={<History />} />
              <Route path="settings" element={<Settings />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </I18nProvider>
  );
}
