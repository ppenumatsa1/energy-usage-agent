-- BR-3: row-level security. The app role is SELECT-only and never the table owner, so it cannot bypass RLS.
-- Unset scope => NULL => no rows (fail closed).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'energy_reader') THEN
        CREATE ROLE energy_reader NOLOGIN;
    END IF;
END
$$;

ALTER TABLE energy.sites          ENABLE ROW LEVEL SECURITY;
ALTER TABLE energy.meters         ENABLE ROW LEVEL SECURITY;
ALTER TABLE energy.usage_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE energy.usage_daily    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS customer_isolation ON energy.sites;
DROP POLICY IF EXISTS customer_isolation ON energy.meters;
DROP POLICY IF EXISTS customer_isolation ON energy.usage_readings;
DROP POLICY IF EXISTS customer_isolation ON energy.usage_daily;

CREATE POLICY customer_isolation ON energy.sites FOR SELECT
    USING (customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid);
CREATE POLICY customer_isolation ON energy.meters FOR SELECT
    USING (customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid);
CREATE POLICY customer_isolation ON energy.usage_readings FOR SELECT
    USING (customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid);
CREATE POLICY customer_isolation ON energy.usage_daily FOR SELECT
    USING (customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid);

REVOKE ALL ON ALL TABLES IN SCHEMA energy FROM PUBLIC;
GRANT USAGE ON SCHEMA energy TO energy_reader;
GRANT SELECT ON energy.sites, energy.meters, energy.usage_readings, energy.usage_daily TO energy_reader;
-- No direct access to customers / user_customer: the mapping is read only via resolve_customer().

CREATE OR REPLACE FUNCTION energy.resolve_customer(p_tid uuid, p_oid uuid)
RETURNS TABLE (customer_id uuid, name text, timezone text)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
    SELECT c.customer_id, c.name, c.timezone
    FROM energy.user_customer uc
    JOIN energy.customers c ON c.customer_id = uc.customer_id
    WHERE uc.tid = p_tid AND uc.oid = p_oid
$$;
REVOKE ALL ON FUNCTION energy.resolve_customer(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION energy.resolve_customer(uuid, uuid) TO energy_reader;
