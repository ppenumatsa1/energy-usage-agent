import type { ChatTurn } from "../hooks/useChat";
import type { ChatResponse } from "../types/api";
import { ErrorRef } from "./ErrorRef";
import { formatDuration, formatTimestamp, plural, relativeTime } from "./format";
import { AlertIcon, ClockIcon, RowsIcon, SparkIcon, ToolIcon } from "./Icons";
import { QuestionChips } from "./QuestionChips";
import { ResultChart } from "./ResultChart";
import { ResultTable } from "./ResultTable";
import { RunProgress } from "./RunProgress";
import { STATUS_META, agentLabel } from "./statusMeta";
import { TracePanel } from "./TracePanel";

interface Props {
  turn: ChatTurn;
  onRetry: (turnId: string) => void;
  onAsk: (question: string) => void;
  busy: boolean;
  expandAll: boolean;
}

function Assumptions({ items }: { items: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="assumptions">
      <h4 className="assumptions__title">Assumptions</h4>
      <ul aria-label="Assumptions">
        {items.map((a, i) => (
          <li key={i}>{a}</li>
        ))}
      </ul>
    </div>
  );
}

function Kpis({ response }: { response: ChatResponse }) {
  const { trace, table } = response;
  return (
    <ul className="kpis" aria-label="Answer details">
      {trace ? (
        <li className="kpi" title="Time to answer">
          <ClockIcon size={13} /> {formatDuration(trace.durationMs)}
        </li>
      ) : null}
      {trace ? (
        <li className="kpi">
          <ToolIcon size={13} /> {plural(trace.steps?.length ?? 0, "tool call")}
        </li>
      ) : null}
      {table ? (
        <li className="kpi">
          <RowsIcon size={13} /> {plural(table.rows?.length ?? 0, "row")}
        </li>
      ) : null}
      <li className="kpi">
        <SparkIcon size={13} /> {agentLabel(trace)}
      </li>
    </ul>
  );
}

interface BodyProps {
  response: ChatResponse;
  onAsk: (question: string) => void;
  onRetry: () => void;
  busy: boolean;
  expandAll: boolean;
}

function ResponseBody({ response, onAsk, onRetry, busy, expandAll }: BodyProps) {
  const { status, table, chart } = response;
  const meta = STATUS_META[status] ?? STATUS_META.ok;
  const showTable = Boolean(table && table.columns?.length && table.rows?.length);
  // Business rule: no chart when there is no data.
  const showChart = Boolean(chart && table && table.rows?.length && status !== "no_data");

  return (
    <>
      <header className="answer__head">
        <span className={`badge badge--${meta.tone}`}>{meta.label}</span>
        {response.createdAt ? (
          <time className="answer__time" dateTime={response.createdAt} title={formatTimestamp(response.createdAt)}>
            {relativeTime(response.createdAt)}
          </time>
        ) : null}
      </header>
      <div className={`answer__text${status === "error" ? " answer__text--error" : ""}`}>{response.answer}</div>
      <Kpis response={response} />
      {showChart && chart && table ? <ResultChart chart={chart} table={table} /> : null}
      {showTable && table ? <ResultTable table={table} caption={chart?.title || "Result"} /> : null}
      <Assumptions items={response.assumptions} />
      {status === "refused" ? (
        <div className="suggestions">
          <p className="suggestions__title">Try one of these instead</p>
          <QuestionChips onPick={onAsk} disabled={busy} label="Suggested questions" />
        </div>
      ) : null}
      {status === "error" ? (
        <div>
          <button type="button" className="btn btn--secondary btn--small" onClick={onRetry} disabled={busy}>
            Retry
          </button>
        </div>
      ) : null}
      <TracePanel response={response} expandAll={expandAll} />
    </>
  );
}

export function AnswerCard({ turn, onRetry, onAsk, busy, expandAll }: Props) {
  const pending = turn.state === "pending";
  return (
    <li className="turn">
      <div className="question">
        <span className="question__label">You asked</span>
        <p className="question__text">{turn.question}</p>
      </div>
      <article className="card answer" aria-label="Answer" aria-live="polite" aria-busy={pending}>
        {pending ? <RunProgress stage={turn.stage} startedAt={turn.startedAt} /> : null}
        {turn.state === "error" && turn.error ? (
          <div className="answer__error" role="alert">
            <header className="answer__head">
              <span className="badge badge--error">
                <AlertIcon size={12} /> Error
              </span>
            </header>
            <p className="answer__text">{turn.error.message}</p>
            <div className="answer__error-actions">
              {turn.error.retryable ? (
                <button
                  type="button"
                  className="btn btn--secondary btn--small"
                  onClick={() => onRetry(turn.id)}
                  disabled={busy}
                >
                  Try again
                </button>
              ) : null}
              <ErrorRef correlationId={turn.error.correlationId} />
            </div>
          </div>
        ) : null}
        {turn.state === "done" && turn.response ? (
          <ResponseBody
            response={turn.response}
            onAsk={onAsk}
            busy={busy}
            onRetry={() => onRetry(turn.id)}
            expandAll={expandAll}
          />
        ) : null}
      </article>
    </li>
  );
}
