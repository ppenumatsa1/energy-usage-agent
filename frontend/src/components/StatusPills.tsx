import type { StatusState } from "../hooks/useStatus";

export function StatusPills({ state }: { state: StatusState }) {
  if (state.status === "loading") return null;
  if (state.status === "error") {
    return (
      <ul className="pills" aria-label="Service status">
        <li className="pill pill--unknown" title="Service status could not be loaded">
          <span className="pill__dot" aria-hidden="true" />
          Status unavailable
        </li>
      </ul>
    );
  }
  return (
    <ul className="pills" aria-label="Service status">
      {state.data.components.map((c) => (
        <li
          key={c.id}
          className={`pill pill--${c.status === "ok" ? "ok" : "down"}`}
          title={c.detail ? `${c.label}: ${c.detail}` : c.label}
        >
          <span className="pill__dot" aria-hidden="true" />
          {c.label}
          {c.status === "ok" ? (
            <span className="visually-hidden"> operational</span>
          ) : (
            <span className="pill__state"> down</span>
          )}
        </li>
      ))}
    </ul>
  );
}
