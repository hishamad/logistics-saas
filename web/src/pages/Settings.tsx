// Settings: your password, the company's users (admins) and the activity trail.
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type AuditRow, type Role, type UserRow } from "../api";
import { useAuth } from "../auth";
import { useI18n, type StringKey } from "../i18n";

const ROLES: Role[] = ["admin", "dispatcher", "viewer"];

export function Settings() {
  const { t } = useI18n();
  const { isAdmin } = useAuth();
  const [changes, setChanges] = useState(0); // reloads the activity after a change here
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("settingsTitle")}</h1>
          <span className="muted">{t("settingsLead")}</span>
        </div>
      </div>
      <div className="settings-grid">
        <Account />
        {isAdmin && <UsersPanel onChanged={() => setChanges((n) => n + 1)} />}
        <Activity reload={changes} />
      </div>
    </>
  );
}

function Account() {
  const { t } = useI18n();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [state, setState] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await api.post("/api/me/password", { current, new: next });
      setState({ ok: true, text: t("passwordChanged") });
      setCurrent("");
      setNext("");
    } catch (caught) {
      setState({ ok: false, text: (caught as Error).message });
    }
  }

  return (
    <section className="panel">
      <h2>{t("accountTitle")}</h2>
      <form onSubmit={submit} className="stack">
        <label className="field">
          <span>{t("currentPassword")}</span>
          <input className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <label className="field">
          <span>{t("newPassword")}</span>
          <input className="input" type="password" autoComplete="new-password" minLength={10} value={next} onChange={(e) => setNext(e.target.value)} required />
        </label>
        <button className="btn btn-primary fit" disabled={!current || next.length < 10}>
          {t("changePassword")}
        </button>
        {state && <div className={`alert ${state.ok ? "alert-ok" : "alert-error"}`}>{state.text}</div>}
      </form>
    </section>
  );
}

function UsersPanel({ onChanged }: { onChanged: () => void }) {
  const { t, date } = useI18n();
  const { me } = useAuth();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState({ name: "", email: "", role: "dispatcher" as Role, password: "" });

  const load = useCallback(() => {
    api
      .get<UserRow[]>("/api/users")
      .then(setUsers)
      .catch((caught: Error) => setError(caught.message));
  }, []);
  useEffect(load, [load]);

  async function act(action: () => Promise<unknown>) {
    setError("");
    try {
      await action();
      load();
      onChanged();
      return true;
    } catch (caught) {
      setError((caught as Error).message);
      return false;
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    if (await act(() => api.post("/api/users", draft))) setDraft({ name: "", email: "", role: "dispatcher", password: "" });
  }

  return (
    <section className="panel settings-wide">
      <h2>{t("usersTitle")}</h2>
      <p className="muted">{t("usersLead")}</p>
      {error && <div className="alert alert-error">{error}</div>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("colName")}</th>
              <th>{t("colEmail")}</th>
              <th>{t("colRole")}</th>
              <th>{t("created")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const self = u.email === me?.user.email;
              return (
                <tr key={u.id} className={u.active ? undefined : "inactive-row"}>
                  <td>
                    {u.name} {self && <span className="muted">({t("you")})</span>}
                  </td>
                  <td>
                    <bdi>{u.email}</bdi>
                  </td>
                  <td>
                    <select className="input compact-input" value={u.role} disabled={self || !u.active} onChange={(e) => void act(() => api.patch(`/api/users/${u.id}`, { role: e.target.value }))}>
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {t(r as StringKey)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>{date(u.created_at, { timeStyle: undefined })}</td>
                  <td>
                    {!self &&
                      (u.active ? (
                        <button className="text-btn quiet" onClick={() => void act(() => api.patch(`/api/users/${u.id}`, { active: false }))}>
                          {t("deactivate")}
                        </button>
                      ) : (
                        <>
                          <span className="badge badge-red">{t("inactive")}</span>{" "}
                          <button className="text-btn" onClick={() => void act(() => api.patch(`/api/users/${u.id}`, { active: true }))}>
                            {t("reactivate")}
                          </button>
                        </>
                      ))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <form className="add-user" onSubmit={add}>
        <h3>{t("addUser")}</h3>
        <div className="form-grid">
          <label className="field">
            <span>{t("colName")}</span>
            <input className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} required />
          </label>
          <label className="field">
            <span>{t("colEmail")}</span>
            <input className="input" type="email" dir="ltr" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} required />
          </label>
          <label className="field">
            <span>{t("colRole")}</span>
            <select className="input" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value as Role })}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(r as StringKey)}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>{t("firstPassword")}</span>
            <input className="input" type="password" autoComplete="new-password" minLength={10} value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} required />
          </label>
        </div>
        <button className="btn btn-primary" disabled={!draft.name || !draft.email || draft.password.length < 10}>
          {t("addUser")}
        </button>
      </form>
    </section>
  );
}

function Activity({ reload }: { reload: number }) {
  const { t, date } = useI18n();
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  useEffect(() => {
    api
      .get<AuditRow[]>("/api/audit")
      .then(setRows)
      .catch(() => setRows([]));
  }, [reload]);
  const detail = (row: AuditRow) =>
    Object.entries(row.detail)
      .filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0))
      .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`)
      .join(" · ");
  return (
    <section className="panel settings-wide">
      <h2>{t("activityTitle")}</h2>
      <p className="muted">{t("activityLead")}</p>
      {rows && rows.length === 0 && <p className="empty">{t("noActivity")}</p>}
      {rows && rows.length > 0 && (
        <div className="table-wrap activity">
          <table>
            <thead>
              <tr>
                <th>{t("colWhen")}</th>
                <th>{t("colBy")}</th>
                <th>{t("colWhat")}</th>
                <th>{t("colDetail")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  <td>{date(row.at)}</td>
                  <td>{row.by ?? "—"}</td>
                  <td>{t(`a_${row.action}` as StringKey) ?? row.action}</td>
                  <td className="muted small wrap-cell" dir="auto">
                    {detail(row)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
