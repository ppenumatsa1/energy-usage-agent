-- app-api schema: conversation ownership (BR-11). No access to the energy schema.
CREATE SCHEMA IF NOT EXISTS app_api;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_api_rw') THEN
        CREATE ROLE app_api_rw NOLOGIN;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS app_api.conversations (
    conversation_id       uuid PRIMARY KEY,
    tid                   uuid NOT NULL,
    oid                   uuid NOT NULL,
    agent_conversation_id text NOT NULL,
    title                 text NOT NULL DEFAULT '',
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conversations_owner_idx ON app_api.conversations (tid, oid, updated_at DESC);

REVOKE ALL ON ALL TABLES IN SCHEMA app_api FROM PUBLIC;
GRANT USAGE ON SCHEMA app_api TO app_api_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON app_api.conversations TO app_api_rw;
