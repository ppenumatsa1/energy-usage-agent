import { useState } from "react";
import type { ConversationSummary } from "../types/api";
import { plural, relativeTime } from "./format";
import { ChatIcon, PlusIcon, TrashIcon } from "./Icons";

interface Props {
  items: ConversationSummary[];
  loaded: boolean;
  activeId?: string;
  error: string | null;
  retentionDays: number;
  onNew: () => void;
  onOpen: (conversationId: string) => void;
  onDelete: (conversationId: string) => void;
}

export function ConversationList({ items, loaded, activeId, error, retentionDays, onNew, onOpen, onDelete }: Props) {
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <nav className="sidebar" aria-label="Conversations">
      <button type="button" className="btn btn--primary btn--block" onClick={onNew}>
        <PlusIcon /> New conversation
      </button>
      <h2 className="sidebar__heading">History</h2>
      {error ? (
        <p className="small error-text" role="alert">
          {error}
        </p>
      ) : null}
      {loaded && items.length === 0 && !error ? (
        <p className="sidebar__empty">No conversations yet. Your questions will appear here.</p>
      ) : null}
      <ul className="conv-list">
        {items.map((c) => {
          const active = c.conversationId === activeId;
          const title = c.title || "Untitled";
          return (
            <li key={c.conversationId} className={`conv${active ? " conv--active" : ""}`}>
              {confirming === c.conversationId ? (
                <div className="conv__confirm" role="group" aria-label={`Delete “${title}”?`}>
                  <span className="conv__confirm-text">Delete this conversation?</span>
                  <div className="conv__confirm-actions">
                    <button
                      type="button"
                      className="btn btn--danger btn--xs"
                      onClick={() => {
                        setConfirming(null);
                        onDelete(c.conversationId);
                      }}
                    >
                      Delete
                    </button>
                    <button type="button" className="btn btn--ghost btn--xs" autoFocus onClick={() => setConfirming(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    className="conv__open"
                    aria-current={active ? "page" : undefined}
                    onClick={() => onOpen(c.conversationId)}
                  >
                    <ChatIcon className="conv__icon" />
                    <span className="conv__body">
                      <span className="conv__title">{title}</span>
                      <span className="conv__meta">
                        {relativeTime(c.updatedAt || c.createdAt)}
                        {typeof c.turnCount === "number" ? ` · ${plural(c.turnCount, "question")}` : ""}
                      </span>
                    </span>
                  </button>
                  <button
                    type="button"
                    className="icon-btn conv__delete"
                    aria-label={`Delete conversation ${title}`}
                    title="Delete conversation"
                    onClick={() => setConfirming(c.conversationId)}
                  >
                    <TrashIcon size={15} />
                  </button>
                </>
              )}
            </li>
          );
        })}
      </ul>
      <p className="sidebar__footer">History kept {plural(retentionDays, "day")}</p>
    </nav>
  );
}
