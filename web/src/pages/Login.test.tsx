import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeApi, show } from "../test/setup";
import { Login } from "./Login";

function signIn() {
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "a@b.test" } });
  fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "secret-pass" } });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
}

describe("sign-in page", () => {
  it("says the email or password is wrong", async () => {
    fakeApi({ "/api/me": { status: 401, body: {} }, "/api/auth/login": { status: 401, body: {} } });
    show(<Login />);
    signIn();
    await waitFor(() => expect(screen.getByText("Wrong email or password.")).toBeTruthy());
  });

  it("says to wait when sign-in is throttled", async () => {
    fakeApi({ "/api/me": { status: 401, body: {} }, "/api/auth/login": { status: 429, body: {} } });
    show(<Login />);
    signIn();
    await waitFor(() => expect(screen.getByText(/Too many failed sign-ins/)).toBeTruthy());
  });

  it("sends the anti-forgery header with the sign-in", async () => {
    const calls = fakeApi({ "/api/me": { status: 401, body: {} }, "/api/auth/login": { status: 401, body: {} } });
    show(<Login />);
    signIn();
    await waitFor(() => expect(calls.some((c) => c.path === "/api/auth/login")).toBe(true));
    const login = calls.find((c) => c.path === "/api/auth/login");
    expect((login?.init?.headers as Record<string, string>)["X-Requested-With"]).toBe("freight");
  });
});
