import { Component, type ErrorInfo, type ReactNode } from "react";
import { describeError } from "../api/problems";
import { ErrorRef } from "./ErrorRef";
import { AlertIcon } from "./Icons";

interface Props {
  children: ReactNode;
}

interface State {
  error: unknown;
  failed: boolean;
}

/** Last-resort boundary: replaces a crashed tree with a friendly panel instead of a blank page. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: undefined, failed: false };

  static getDerivedStateFromError(error: unknown): State {
    return { error, failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const { correlationId } = describeError(this.state.error);
    return (
      <main className="center-screen" id="main">
        <section className="panel" role="alert">
          <span className="panel__icon panel__icon--error" aria-hidden="true">
            <AlertIcon size={20} />
          </span>
          <h1>Something went wrong</h1>
          <p>The page hit an unexpected problem. Reloading usually fixes it.</p>
          <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
            Reload
          </button>
          <ErrorRef correlationId={correlationId} />
        </section>
      </main>
    );
  }
}
