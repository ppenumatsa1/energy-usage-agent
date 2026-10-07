import { useState } from "react";

/** Small, copyable correlation ID shown next to errors so users can quote it to support. */
export function ErrorRef({ correlationId }: { correlationId?: string }) {
  const [copied, setCopied] = useState(false);
  if (!correlationId) return null;
  const copy = () => {
    navigator.clipboard
      ?.writeText(correlationId)
      .then(() => setCopied(true))
      .catch(() => undefined);
  };
  return (
    <span className="ref">
      Ref <code className="ref__id">{correlationId}</code>{" "}
      <button type="button" className="ref__copy" onClick={copy} aria-label="Copy reference ID">
        {copied ? "Copied" : "Copy"}
      </button>
    </span>
  );
}
