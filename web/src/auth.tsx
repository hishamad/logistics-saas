// Who is logged in. The session itself is an HttpOnly cookie the page never sees.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type Me } from "./api";

type Auth = {
  me: Me | null;
  loading: boolean;
  canPlan: boolean; // admins and dispatchers; viewers only look
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const Context = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<Me>("/api/me")
      .then(setMe)
      .catch((error) => {
        if (!(error instanceof ApiError && error.status === 401)) console.error(error);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setMe(await api.post<Me>("/api/auth/login", { email, password }));
  }, []);

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    setMe(null);
  }, []);

  const canPlan = !!me && me.user.role !== "viewer";
  const isAdmin = me?.user.role === "admin";
  return <Context.Provider value={{ me, loading, canPlan, isAdmin, login, logout }}>{children}</Context.Provider>;
}

export function useAuth(): Auth {
  const value = useContext(Context);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}
