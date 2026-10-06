import { InfoIcon } from "./Icons";

export function NotOnboarded({ userName, onSignOut }: { userName?: string | null; onSignOut: () => void }) {
  return (
    <main className="center-screen" id="main">
      <section className="panel" aria-labelledby="not-onboarded-title">
        <span className="panel__icon panel__icon--info" aria-hidden="true">
          <InfoIcon size={20} />
        </span>
        <h1 id="not-onboarded-title">Your account isn't set up yet</h1>
        <p>{userName ? `${userName}, your` : "Your"} account isn't set up yet. Contact your administrator.</p>
        <p className="panel__note">
          Once your account is linked to your sites and meters, sign in again to see your energy usage.
        </p>
        <button type="button" className="btn btn--secondary" onClick={onSignOut}>
          Sign out
        </button>
      </section>
    </main>
  );
}
