"use client";

import { createContext, useContext } from "react";

export type Language = "en" | "ar";
export const LocaleContext = createContext<Language>("en");
export function useLocale() {
  const lang = useContext(LocaleContext);
  const locale = lang === "ar" ? "ar-SA" : "en-GB";
  return {
    lang,
    t: (en: string, ar: string) => (lang === "ar" ? ar : en),
    time: (iso: string) =>
      new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "Asia/Riyadh",
      }).format(new Date(iso)),
    date: (iso: string) =>
      new Intl.DateTimeFormat(locale, {
        day: "numeric",
        month: "short",
        timeZone: "Asia/Riyadh",
      }).format(new Date(iso)),
    money: (minor: number | null | undefined) =>
      minor == null
        ? "—"
        : new Intl.NumberFormat(locale, {
            maximumFractionDigits: 2,
            minimumFractionDigits: 2,
          }).format(minor / 100),
    num: (value: number) =>
      new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value),
  };
}
