import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { SendIcon } from "./Icons";

export const MAX_LENGTH = 2000;
const COUNTER_FROM = 1500;

export function Composer({ onSend, disabled }: { onSend: (message: string) => void; disabled: boolean }) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const refocus = useRef(false);

  useEffect(() => {
    if (!disabled && refocus.current) {
      refocus.current = false;
      inputRef.current?.focus();
    }
  }, [disabled]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const message = text.trim();
    if (!message || disabled) return;
    refocus.current = document.activeElement === inputRef.current;
    onSend(message);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const length = text.length;
  const counterTone = length >= MAX_LENGTH ? " composer__count--max" : length >= MAX_LENGTH * 0.9 ? " composer__count--near" : "";

  return (
    <form className="composer" onSubmit={submit}>
      <div className={`composer__card${disabled ? " composer__card--disabled" : ""}`}>
        <label htmlFor="question" className="visually-hidden">
          Ask about your energy usage
        </label>
        <textarea
          id="question"
          ref={inputRef}
          rows={2}
          maxLength={MAX_LENGTH}
          placeholder="Ask about your energy usage, e.g. “Compare this month vs last month.”"
          value={text}
          disabled={disabled}
          aria-describedby="composer-hint"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="composer__bar">
          <span className="composer__hint" id="composer-hint">
            {disabled ? "Working on your question…" : "Enter to send · Shift+Enter for a new line"}
          </span>
          {length >= COUNTER_FROM ? (
            <span className={`composer__count${counterTone}`} aria-live="polite">
              {length.toLocaleString()} / {MAX_LENGTH.toLocaleString()}
            </span>
          ) : null}
          <button type="submit" className="btn btn--primary btn--small" disabled={disabled || !text.trim()}>
            Send <SendIcon size={14} />
          </button>
        </div>
      </div>
    </form>
  );
}
