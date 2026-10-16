// Test helpers: the app's providers around a component, and a fake API.
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth";
import { I18nProvider, type Language } from "../i18n";

type Reply = { status?: number; body: unknown };

/** Answers fetch() by URL path; anything unexpected fails loudly. */
export function fakeApi(routes: Record<string, Reply | ((init?: RequestInit) => Reply)>) {
  const calls: { path: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const path = input.split("?")[0];
      calls.push({ path, init });
      const route = routes[path];
      if (!route) throw new Error(`Unexpected request: ${path}`);
      const reply = typeof route === "function" ? route(init) : route;
      return new Response(JSON.stringify(reply.body), { status: reply.status ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

export const ME = (role: "admin" | "dispatcher" | "viewer" = "dispatcher") => ({
  body: { user: { name: "Test User", email: "t@carrier.test", role }, company: { name: "Test Carrier" } },
});

export function show(ui: ReactElement, language: Language = "en", path = "/") {
  localStorage.setItem("lang", language);
  return render(
    <I18nProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
      </AuthProvider>
    </I18nProvider>,
  );
}
