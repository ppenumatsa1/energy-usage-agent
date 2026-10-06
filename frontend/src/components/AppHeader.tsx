import type { StatusState } from "../hooks/useStatus";
import { BoltIcon } from "./Icons";
import { StatusPills } from "./StatusPills";

interface Props {
  userLabel?: string | null;
  customerName?: string | null;
  timezone?: string | null;
  status?: StatusState;
  onSignOut?: () => void;
}

function initials(name: string): string {
  const letters = name
    .split(/[\s·]+/)
    .filter((w) => /^[\p{L}\p{N}]/u.test(w))
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase());
  return letters.join("") || "?";
}

export function AppHeader({ userLabel, customerName, timezone, status, onSignOut }: Props) {
  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand__tile" aria-hidden="true">
          <BoltIcon size={18} />
        </span>
        <div className="brand__text">
          <span className="brand__title">Energy usage assistant</span>
          <span className="brand__subtitle">Ask about your sites and meters · answers come from your metered data</span>
        </div>
      </div>
      {onSignOut ? (
        <div className="app-header__right">
          {status ? <StatusPills state={status} /> : null}
          <div className="user">
            {userLabel ? (
              <span className="user__avatar" aria-hidden="true">
                {initials(userLabel)}
              </span>
            ) : null}
            <div className="user__text">
              {userLabel ? <span className="user__name">{userLabel}</span> : null}
              {customerName ? (
                <span className="user__meta">
                  {customerName}
                  {timezone ? ` · ${timezone}` : ""}
                </span>
              ) : null}
            </div>
            <button type="button" className="btn btn--ghost btn--small" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </header>
  );
}
