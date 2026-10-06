import { useEffect, useState } from "react";
import type { ChatStage, StatusEvent } from "../types/api";
import { CheckIcon } from "./Icons";
import { stageText } from "./stageText";

const STEPS: { stage: ChatStage; label: string }[] = [
  { stage: "thinking", label: "Thinking" },
  { stage: "tool", label: "Calling tools" },
  { stage: "composing", label: "Composing" },
];

/** Horizontal Thinking → Calling tools → Composing progress shown while a turn runs. */
export function RunProgress({ stage, startedAt }: { stage?: StatusEvent; startedAt?: number }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, []);

  const active = Math.max(0, STEPS.findIndex((s) => s.stage === (stage?.stage ?? "thinking")));
  const elapsed = startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0;

  return (
    <div className="progress">
      <ol className="progress__steps" aria-label="Progress">
        {STEPS.map((s, i) => {
          const state = i < active ? "done" : i === active ? "active" : "todo";
          return (
            <li key={s.stage} className={`progress__step progress__step--${state}`} aria-current={i === active ? "step" : undefined}>
              <span className="progress__dot" aria-hidden="true">
                {state === "done" ? <CheckIcon size={12} strokeWidth={3} /> : i + 1}
              </span>
              <span className="progress__label">
                {s.label}
                {s.stage === "tool" && stage?.stage === "tool" && stage.tool ? (
                  <code className="progress__tool">{stage.tool}</code>
                ) : null}
              </span>
              <span className="visually-hidden">{state === "done" ? " (done)" : state === "active" ? " (in progress)" : ""}</span>
            </li>
          );
        })}
      </ol>
      <span className="progress__elapsed" aria-hidden="true">
        {elapsed} s
      </span>
      <p className="progress__text" role="status" aria-live="polite">
        {stageText(stage)}
      </p>
    </div>
  );
}
