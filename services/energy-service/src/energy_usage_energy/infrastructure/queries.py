"""SQL text. Only ever executed on an RLS-scoped connection (see postgres.rls_session)."""

RESOLVE_CUSTOMER = (
    "SELECT customer_id, name, timezone FROM energy.resolve_customer(%(tid)s::uuid, %(oid)s::uuid)"
)

SET_CUSTOMER_SCOPE = "SELECT set_config('app.customer_id', %(customer_id)s, true)"

_FILTERS = """
  AND (%(site_id)s::text IS NULL OR {alias}site_id = %(site_id)s::text)
  AND (%(meter_id)s::text IS NULL OR {alias}meter_id = %(meter_id)s::text)
"""

SERIES_DAILY = (
    """
SELECT date_trunc(%(unit)s, d.day::timestamp)::date AS period, sum(d.kwh)::float8 AS kwh
FROM energy.usage_daily d
WHERE d.day BETWEEN %(start)s AND %(end)s"""
    + _FILTERS.format(alias="d.")
    + """
GROUP BY 1 ORDER BY 1
"""
)

SERIES_HOURLY = (
    """
SELECT date_trunc('hour', r.ts AT TIME ZONE %(tz)s) AS period, sum(r.kwh)::float8 AS kwh
FROM energy.usage_readings r
JOIN energy.meters m ON m.meter_id = r.meter_id
WHERE r.ts >= %(start_utc)s AND r.ts < %(end_utc)s"""
    + _FILTERS.format(alias="m.")
    + """
GROUP BY 1 ORDER BY 1
"""
)

BREAKDOWN_SITE = """
SELECT s.site_id AS group_id, s.name AS group_name,
       CASE WHEN %(unit)s = 'total' THEN NULL ELSE date_trunc(%(unit_or_day)s, d.day::timestamp)::date END AS period,
       sum(d.kwh)::float8 AS kwh
FROM energy.usage_daily d JOIN energy.sites s ON s.site_id = d.site_id
WHERE d.day BETWEEN %(start)s AND %(end)s
GROUP BY 1, 2, 3 ORDER BY 3 NULLS FIRST, 1
"""

BREAKDOWN_METER = """
SELECT m.meter_id AS group_id, m.name AS group_name,
       CASE WHEN %(unit)s = 'total' THEN NULL ELSE date_trunc(%(unit_or_day)s, d.day::timestamp)::date END AS period,
       sum(d.kwh)::float8 AS kwh
FROM energy.usage_daily d JOIN energy.meters m ON m.meter_id = d.meter_id
WHERE d.day BETWEEN %(start)s AND %(end)s
GROUP BY 1, 2, 3 ORDER BY 3 NULLS FIRST, 1
"""

SITES_AND_METERS = """
SELECT s.site_id, s.name AS site_name, s.city, m.meter_id, m.name AS meter_name, m.type AS meter_type
FROM energy.sites s JOIN energy.meters m ON m.site_id = s.site_id
ORDER BY s.site_id, m.meter_id
"""

DAYS_WITH_DATA = "SELECT DISTINCT day FROM energy.usage_daily WHERE day BETWEEN %(start)s AND %(end)s"
