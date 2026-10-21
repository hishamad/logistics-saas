// Night or daylight. Follows the computer's setting until the user picks one.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Theme = "night" | "day";

type ThemeValue = { theme: Theme; toggle: () => void };

const Context = createContext<ThemeValue | null>(null);

function stored(): Theme | null {
  try {
    const value = localStorage.getItem("theme");
    return value === "night" || value === "day" ? value : null;
  } catch {
    return null;
  }
}

function fromSystem(): Theme {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: light)").matches ? "day" : "night";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [chosen, setChosen] = useState<Theme | null>(stored);
  const [system, setSystem] = useState<Theme>(fromSystem);
  const theme = chosen ?? system;

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: light)");
    if (!query) return;
    const follow = () => setSystem(query.matches ? "day" : "night");
    query.addEventListener("change", follow);
    return () => query.removeEventListener("change", follow);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const value = useMemo<ThemeValue>(
    () => ({
      theme,
      toggle: () => {
        const next = theme === "night" ? "day" : "night";
        setChosen(next);
        try {
          localStorage.setItem("theme", next);
        } catch {
          // private mode: the choice lasts for this visit only
        }
      },
    }),
    [theme],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useTheme(): ThemeValue {
  const value = useContext(Context);
  if (!value) throw new Error("useTheme outside ThemeProvider");
  return value;
}
