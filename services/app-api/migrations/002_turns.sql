-- app-api schema: stored conversation turns so a reopened conversation shows what the user saw.
-- Holds the user's own question and the answer payload (text, table rows, chart, trace). Retention is
-- enforced by the app (default 30 days since last activity); deleting a conversation cascades here.
CREATE TABLE IF NOT EXISTS app_api.turns (
    turn_id         bigserial PRIMARY KEY,
    conversation_id uuid NOT NULL REFERENCES app_api.conversations (conversation_id) ON DELETE CASCADE,
    question        text NOT NULL,
    response        jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS turns_conversation_idx ON app_api.turns (conversation_id, turn_id);
CREATE INDEX IF NOT EXISTS conversations_updated_idx ON app_api.conversations (updated_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON app_api.turns TO app_api_rw;
GRANT USAGE, SELECT ON SEQUENCE app_api.turns_turn_id_seq TO app_api_rw;
