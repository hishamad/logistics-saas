import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { I18nProvider, STRINGS, useI18n, type Language } from "./i18n";

function Probe() {
  const { money, number, span, fill, lang } = useI18n();
  return (
    <p data-testid="out">
      {[lang, money(123456), number(1234567), span(125), fill("descCustomer", { truck: "T1", customer: "C" })].join(" | ")}
    </p>
  );
}

function shown(language: Language) {
  localStorage.setItem("lang", language);
  render(
    <I18nProvider>
      <Probe />
    </I18nProvider>,
  );
  return screen.getByTestId("out").textContent;
}

describe("translations", () => {
  it("has every string in both languages, none empty", () => {
    const english = Object.keys(STRINGS.en).sort();
    expect(Object.keys(STRINGS.ar).sort()).toEqual(english);
    for (const language of ["en", "ar"] as const) {
      for (const [key, value] of Object.entries(STRINGS[language])) expect(value, `${language}.${key}`).not.toBe("");
    }
  });

  it("formats money, numbers and durations per language with Western digits", () => {
    expect(shown("en")).toBe("en | SAR 1,235 | 1,234,567 | 2h 5m | T1 serves only C");
    expect(document.documentElement.dir).toBe("ltr");
  });

  it("switches the whole page to right-to-left in Arabic", () => {
    expect(shown("ar")).toBe("ar | 1,235 ريال | 1,234,567 | 2 س 5 د | T1 تخدم C فقط");
    expect(document.documentElement.dir).toBe("rtl");
  });
});
