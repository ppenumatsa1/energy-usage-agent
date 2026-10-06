-- energy-service schema. Applied by scripts/migrate.py as the table owner (never as the app role).
CREATE SCHEMA IF NOT EXISTS energy;

CREATE TABLE IF NOT EXISTS energy.customers (
    customer_id uuid PRIMARY KEY,
    name        text NOT NULL,
    timezone    text NOT NULL,              -- IANA, e.g. America/Chicago
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS energy.user_customer (
    tid         uuid NOT NULL,
    oid         uuid NOT NULL,
    customer_id uuid NOT NULL REFERENCES energy.customers (customer_id) ON DELETE CASCADE,
    role        text NOT NULL DEFAULT 'viewer',
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tid, oid)
);

CREATE TABLE IF NOT EXISTS energy.sites (
    site_id     text PRIMARY KEY,
    customer_id uuid NOT NULL REFERENCES energy.customers (customer_id) ON DELETE CASCADE,
    name        text NOT NULL,
    city        text
);
CREATE INDEX IF NOT EXISTS sites_customer_idx ON energy.sites (customer_id);

CREATE TABLE IF NOT EXISTS energy.meters (
    meter_id    text PRIMARY KEY,
    customer_id uuid NOT NULL REFERENCES energy.customers (customer_id) ON DELETE CASCADE,
    site_id     text NOT NULL REFERENCES energy.sites (site_id) ON DELETE CASCADE,
    name        text NOT NULL,
    type        text
);
CREATE INDEX IF NOT EXISTS meters_customer_idx ON energy.meters (customer_id);

CREATE TABLE IF NOT EXISTS energy.usage_readings (
    customer_id uuid NOT NULL REFERENCES energy.customers (customer_id) ON DELETE CASCADE,
    meter_id    text NOT NULL REFERENCES energy.meters (meter_id) ON DELETE CASCADE,
    ts          timestamptz NOT NULL,       -- interval start, 15-minute intervals
    kwh         numeric(12, 4) NOT NULL,
    PRIMARY KEY (meter_id, ts)
);
CREATE INDEX IF NOT EXISTS usage_readings_customer_ts_idx ON energy.usage_readings (customer_id, ts);

CREATE TABLE IF NOT EXISTS energy.usage_daily (
    customer_id uuid NOT NULL REFERENCES energy.customers (customer_id) ON DELETE CASCADE,
    site_id     text NOT NULL,
    meter_id    text NOT NULL REFERENCES energy.meters (meter_id) ON DELETE CASCADE,
    day         date NOT NULL,              -- local day in the customer's time zone
    kwh         numeric(14, 4) NOT NULL,
    PRIMARY KEY (meter_id, day)
);
CREATE INDEX IF NOT EXISTS usage_daily_customer_day_idx ON energy.usage_daily (customer_id, day);
