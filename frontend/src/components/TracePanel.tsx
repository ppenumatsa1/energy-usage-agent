import { useId, useState } from "react";
import type { ChatResponse, TraceCheck, TraceStep } from "../types/api";
import { formatDuration, formatTimestamp, plural } from "./format";
import { BlockIcon, CheckIcon, ChevronIcon, InfoIcon } from "./Icons";
import { STATUS_META, agentLabel } from "./statusMeta";

const MAX_ARG_LENGTH = 64;

function argText(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (Array.isArray(value)) return value.map(argText).join(", ");
  if (typeof value === "object") {
    const inner = Object.entries(value as Record<string, unknown>).map(([k, v]) => `${k}: ${argText(v)}`);
    return `{ ${inner.join(", ")} }`;
  }
  return String(value);
}

function Args({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args ?? {});
  if (!entries.length) return <span className="step__noargs">no arguments</span>;
  return (
    <ul className="args" aria-label="Arguments">
      {entries.map(([key, value]) => {
        const text = argText(value);
        const short = text.length > MAX_ARG_LENGTH ? `${text.slice(0, MAX_ARG_LENGTH - 1)}…` : text;
        return (
          <li key={key} className="arg" title={short === text ? undefined : text}>
            <span className="arg__key">{key}:</span> {short}
          </li>
        );
      })}
    </ul>
  );
}

function ToolStep({ step, index }: { step: TraceStep; index: number }) {
  const failed = step.status === "error";
  return (
    <li className={`step${failed ? " step--error" : ""}`}>
      <span className="step__marker" aria-hidden="true">
        {index}
      </span>
      <div className="step__main">
        <div className="step__title">
          <code className="step__tool">{step.tool}</code>
        </div>
        <Args args={step.arguments} />
      </div>
      <div className="step__meta">
        <span className="step__duration">{formatDuration(step.durationMs)}</span>
        {step.rows !== null && step.rows !== undefined ? <span className="step__rows">{plural(step.rows, "row")}</span> : null}
        {failed ? (
          <span className="badge badge--error">error{step.errorCode ? ` ${step.errorCode}` : ""}</span>
        ) : (
          <span className="badge badge--ok">completed</span>
        )}
      </div>
    </li>
  );
}

const CHECK_ICON = { pass: CheckIcon, info: InfoIcon, blocked: BlockIcon } as const;
const CHECK_TEXT = { pass: "Passed", info: "Info", blocked: "Blocked" } as const;

function Check({ check }: { check: TraceCheck }) {
  const Icon = CHECK_ICON[check.outcome] ?? InfoIcon;
  return (
    <li className={`check check--${check.outcome}`}>
      <span className="check__icon" aria-hidden="true">
        <Icon size={13} strokeWidth={2.5} />
      </span>
      <div className="check__text">
        <span className="check__name">{check.name}</span>
        {check.detail ? <span className="check__detail">{check.detail}</span> : null}
      </div>
      <span className="check__outcome">{CHECK_TEXT[check.outcome] ?? check.outcome}</span>
    </li>
  );
}

interface Props {
  response: ChatResponse;
  /** Global "Show details" toggle; changing it opens/closes every panel. */
  expandAll: boolean;
}

export function TracePanel({ response, expandAll }: Props) {
  const [open, setOpen] = useState(expandAll);
  const [lastExpandAll, setLastExpandAll] = useState(expandAll);
  if (lastExpandAll !== expandAll) {
    setLastExpandAll(expandAll);
    setOpen(expandAll);
  }
  const bodyId = useId();
  const trace = response.trace;
  const steps = trace?.steps ?? [];
  const checks = trace?.checks ?? [];

  return (
    <section className={`trace${open ? " trace--open" : ""}`}>
      <button
        type="button"
        className="trace__toggle"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronIcon className="trace__chevron" size={14} />
        <span className="trace__label">How this was answered</span>
        <span className="trace__summary">
          {plural(steps.length, "tool call")} · {plural(checks.length, "check")}
        </span>
      </button>
      {open ? (
        <div className="trace__body" id={bodyId}>
          <h4 className="trace__heading">Agent and tool calls</h4>
          <ol className="steps">
            <li className="step">
              <span className="step__marker" aria-hidden="true">
                1
              </span>
              <div className="step__main">
                <div className="step__title">Understood question</div>
                <div className="step__sub">{agentLabel(trace)}</div>
              </div>
            </li>
            {steps.map((step, i) => (
              <ToolStep key={i} step={step} index={i + 2} />
            ))}
            <li className="step">
              <span className="step__marker" aria-hidden="true">
                {steps.length + 2}
              </span>
              <div className="step__main">
                <div className="step__title">Composed answer</div>
                <div className="step__sub">{STATUS_META[response.status]?.label ?? response.status}</div>
              </div>
              <div className="step__meta">
                {trace ? <span className="step__duration">total {formatDuration(trace.durationMs)}</span> : null}
              </div>
            </li>
          </ol>
          {checks.length ? (
            <>
              <h4 className="trace__heading">Guardrails</h4>
              <ul className="checks">
                {checks.map((c, i) => (
                  <Check key={i} check={c} />
                ))}
              </ul>
            </>
          ) : null}
          <p className="trace__footer">
            <span>
              correlation <code>{response.correlationId}</code>
            </span>
            {response.createdAt ? <span>{formatTimestamp(response.createdAt)}</span> : null}
          </p>
        </div>
      ) : null}
    </section>
  );
}
