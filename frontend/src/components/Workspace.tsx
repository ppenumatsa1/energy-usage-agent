import { errorMessage } from "../api/problems";
import { useAuth } from "../auth/context";
import { useApi } from "../hooks/useApi";
import { useMe } from "../hooks/useMe";
import { useStatus } from "../hooks/useStatus";
import { AppHeader } from "./AppHeader";
import { ChatWorkspace } from "./ChatWorkspace";
import { AlertIcon } from "./Icons";
import { NotOnboarded } from "./NotOnboarded";
import { Spinner } from "./Spinner";

const DEFAULT_RETENTION_DAYS = 30;

export function Workspace() {
  const auth = useAuth();
  const api = useApi();
  const { state, reload } = useMe(api);
  const status = useStatus(api);
  const retentionDays = status.status === "ready" ? status.data.historyRetentionDays : DEFAULT_RETENTION_DAYS;

  if (state.status === "not_onboarded") {
    const me = state.me;
    return (
      <>
        <AppHeader userLabel={me?.userName ?? auth.userLabel} status={status} onSignOut={auth.signOut} />
        <NotOnboarded userName={me?.userName} onSignOut={auth.signOut} />
      </>
    );
  }

  const me = state.status === "ready" ? state.me : null;

  return (
    <>
      <AppHeader
        userLabel={me?.userName ?? auth.userLabel}
        customerName={me?.customerName}
        timezone={me?.timezone}
        status={status}
        onSignOut={auth.signOut}
      />
      {state.status === "loading" ? (
        <main className="center-screen" id="main">
          <Spinner label="Loading your account…" />
        </main>
      ) : null}
      {state.status === "error" ? (
        <main className="center-screen" id="main">
          <section className="panel" role="alert">
            <span className="panel__icon panel__icon--error" aria-hidden="true">
              <AlertIcon size={20} />
            </span>
            <h1>We couldn't load your account</h1>
            <p>{errorMessage(state.error)}</p>
            <button type="button" className="btn btn--primary" onClick={reload}>
              Try again
            </button>
          </section>
        </main>
      ) : null}
      {state.status === "ready" ? <ChatWorkspace api={api} retentionDays={retentionDays} /> : null}
    </>
  );
}
