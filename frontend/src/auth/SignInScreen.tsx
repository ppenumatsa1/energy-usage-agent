import { BoltIcon } from "../components/Icons";
import { useAuth } from "./context";

export function SignInScreen() {
  const auth = useAuth();
  return (
    <main className="center-screen" id="main">
      <section className="panel" aria-labelledby="sign-in-title">
        <span className="panel__icon" aria-hidden="true">
          <BoltIcon size={20} />
        </span>
        <h1 id="sign-in-title">Energy Usage Assistant</h1>
        <p>Ask questions about your energy usage in plain English and get answers straight from your metered data.</p>
        <button type="button" className="btn btn--primary btn--block" disabled={auth.isBusy} onClick={() => void auth.signIn()}>
          Sign in with your work account
        </button>
      </section>
    </main>
  );
}
