import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiClient } from "../api/client";
import { useChat, type HistoryState } from "../hooks/useChat";
import { useConversations } from "../hooks/useConversations";
import { AnswerCard } from "./AnswerCard";
import { Composer } from "./Composer";
import { ConversationList } from "./ConversationList";
import { plural } from "./format";
import { AlertIcon, BoltIcon, CloseIcon, InfoIcon, MenuIcon } from "./Icons";
import { QuestionChips } from "./QuestionChips";

interface Props {
  api: ApiClient;
  retentionDays: number;
}

function EmptyState({ onAsk, disabled }: { onAsk: (q: string) => void; disabled: boolean }) {
  return (
    <div className="empty">
      <span className="empty__tile" aria-hidden="true">
        <BoltIcon size={22} />
      </span>
      <h2 className="empty__title">What would you like to know about your energy use?</h2>
      <p className="empty__text">
        Ask in plain English. Each answer comes with a short summary, a table and — when it helps — a chart, all
        computed from your metered data. Open “How this was answered” to see every tool call behind it.
      </p>
      <QuestionChips variant="cards" onPick={onAsk} disabled={disabled} label="Sample questions" />
    </div>
  );
}

function HistoryNotice({ history, onRetry, onNew }: { history: HistoryState; onRetry: () => void; onNew: () => void }) {
  if (history.status === "loading") {
    return (
      <div className="history-loading" role="status">
        <span className="visually-hidden">Loading conversation…</span>
        {[0, 1].map((i) => (
          <div key={i} className="skeleton-turn" aria-hidden="true">
            <div className="skeleton skeleton--q" />
            <div className="card skeleton-card">
              <div className="skeleton skeleton--badge" />
              <div className="skeleton skeleton--line" />
              <div className="skeleton skeleton--line skeleton--short" />
              <div className="skeleton skeleton--block" />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (history.status !== "error") return null;
  return (
    <div className="card notice notice--error" role="alert">
      <AlertIcon size={18} className="notice__icon" />
      <div>
        <p className="notice__title">{history.notFound ? "Conversation not found" : "Couldn't load this conversation"}</p>
        <p className="notice__text">{history.message}</p>
        <div className="notice__actions">
          {!history.notFound ? (
            <button type="button" className="btn btn--secondary btn--small" onClick={onRetry}>
              Try again
            </button>
          ) : null}
          <button type="button" className="btn btn--primary btn--small" onClick={onNew}>
            Start a new conversation
          </button>
        </div>
      </div>
    </div>
  );
}

export function ChatWorkspace({ api, retentionDays }: Props) {
  const conversations = useConversations(api);
  const chat = useChat(api, { onAnswered: conversations.refresh, onMissing: conversations.drop });
  const [expandAll, setExpandAll] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [lastOpened, setLastOpened] = useState<string | undefined>();
  const endRef = useRef<HTMLDivElement>(null);
  const turnsRef = useRef<HTMLOListElement>(null);
  const lastKey = useRef("");

  useEffect(() => {
    // Follow a new question to the bottom; when its answer (or loaded history) arrives, show that answer from the top.
    const last = chat.turns[chat.turns.length - 1];
    const key = last ? `${last.id}:${last.state}` : "";
    if (key === lastKey.current) return;
    lastKey.current = key;
    if (!last) return;
    if (last.state === "pending") {
      endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
    } else {
      const element = turnsRef.current?.lastElementChild as HTMLElement | null | undefined;
      element?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }
  }, [chat.turns]);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  const { openConversation, newChat } = chat;
  const open = useCallback(
    (id: string) => {
      setLastOpened(id);
      setNavOpen(false);
      openConversation(id);
    },
    [openConversation],
  );
  const startNew = useCallback(() => {
    setNavOpen(false);
    newChat();
  }, [newChat]);

  const remove = (id: string) => {
    if (id === chat.conversationId) chat.newChat();
    void conversations.remove(id);
  };

  const summary = conversations.items.find((c) => c.conversationId === chat.conversationId);
  const title = chat.conversationId
    ? chat.title || summary?.title || chat.turns[0]?.question || "Conversation"
    : chat.turns[0]?.question || "New conversation";
  const answered = chat.turns.filter((t) => t.response).length;
  const composerDisabled = chat.isBusy || (chat.history.status === "error" && !chat.history.notFound);
  const showEmpty = !chat.conversationId && chat.turns.length === 0 && chat.history.status !== "error";

  return (
    <div className={`workspace${navOpen ? " workspace--nav-open" : ""}`}>
      <ConversationList
        items={conversations.items}
        loaded={conversations.loaded}
        activeId={chat.conversationId}
        error={conversations.error}
        retentionDays={retentionDays}
        onNew={startNew}
        onOpen={open}
        onDelete={remove}
      />
      {navOpen ? <div className="scrim" aria-hidden="true" onClick={() => setNavOpen(false)} /> : null}
      <main className="chat" id="main">
        <div className="toolbar">
          <button
            type="button"
            className="icon-btn toolbar__nav"
            aria-label={navOpen ? "Hide conversations" : "Show conversations"}
            aria-expanded={navOpen}
            onClick={() => setNavOpen((o) => !o)}
          >
            {navOpen ? <CloseIcon size={18} /> : <MenuIcon size={18} />}
          </button>
          <div className="toolbar__title">
            <h1 className="toolbar__heading">{title}</h1>
            {answered ? <span className="toolbar__meta">{plural(answered, "answer")}</span> : null}
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={expandAll}
            className={`switch${expandAll ? " switch--on" : ""}`}
            onClick={() => setExpandAll((v) => !v)}
          >
            <span className="switch__track" aria-hidden="true">
              <span className="switch__thumb" />
            </span>
            Show details
          </button>
        </div>
        <div className="thread">
          <div className="thread__inner">
            {showEmpty ? <EmptyState onAsk={chat.send} disabled={chat.isBusy} /> : null}
            <HistoryNotice
              history={chat.history}
              onRetry={() => lastOpened && open(lastOpened)}
              onNew={startNew}
            />
            {chat.historyMissing ? (
              <div className="card notice">
                <InfoIcon size={18} className="notice__icon" />
                <div>
                  <p className="notice__title">No saved messages</p>
                  <p className="notice__text">
                    Earlier messages from this conversation weren't saved. Follow-up questions still keep their context.
                  </p>
                </div>
              </div>
            ) : null}
            {chat.turns.length ? (
              <ol className="turns" aria-label="Conversation" ref={turnsRef}>
                {chat.turns.map((turn) => (
                  <AnswerCard
                    key={turn.id}
                    turn={turn}
                    onRetry={chat.retry}
                    onAsk={chat.send}
                    busy={chat.isBusy}
                    expandAll={expandAll}
                  />
                ))}
              </ol>
            ) : null}
            <div ref={endRef} />
          </div>
        </div>
        <div className="composer-dock">
          <Composer onSend={chat.send} disabled={composerDisabled} />
        </div>
      </main>
    </div>
  );
}
