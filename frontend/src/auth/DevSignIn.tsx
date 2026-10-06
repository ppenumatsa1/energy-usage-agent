import { useEffect, useState } from "react";
import { getDevUsers } from "../api/client";
import { errorMessage } from "../api/problems";
import { ChevronIcon } from "../components/Icons";
import { Spinner } from "../components/Spinner";
import type { DevUser } from "../types/api";
import { useAuth } from "./context";

export function DevSignIn() {
  const auth = useAuth();
  const [users, setUsers] = useState<DevUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDevUsers()
      .then((list) => !cancelled && setUsers(list))
      .catch((err: unknown) => !cancelled && setError(errorMessage(err)));
    return () => {
      cancelled = true;
    };
  }, []);

  const choose = async (user: DevUser) => {
    setError(null);
    try {
      await auth.signIn(user.id, user.label);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <main className="center-screen" id="main">
      <section className="panel" aria-labelledby="dev-sign-in-title">
        <span className="panel__badge">Local development</span>
        <h1 id="dev-sign-in-title">Dev sign-in</h1>
        <p className="panel__note">Choose a synthetic demo user to sign in as.</p>
        {error ? (
          <p className="error-text" role="alert">
            {error}
          </p>
        ) : null}
        {!users && !error ? <Spinner label="Loading users…" /> : null}
        {users ? (
          <ul className="dev-users">
            {users.map((u) => (
              <li key={u.id}>
                <button type="button" className="dev-user" disabled={auth.isBusy} onClick={() => void choose(u)}>
                  <span className="dev-user__avatar" aria-hidden="true">
                    {u.id.slice(0, 2).toUpperCase()}
                  </span>
                  <span className="dev-user__label">{u.label}</span>
                  <ChevronIcon size={16} className="dev-user__chevron" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </main>
  );
}
