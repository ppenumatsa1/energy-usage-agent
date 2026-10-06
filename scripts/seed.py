"""Load SYNTHETIC demo data (3 made-up customers, 2 made-up tenants). Never load real data with this.

Incremental by default: a customer that already exists keeps its data and user mappings; only the days
after its newest reading, up to yesterday, are appended (so relative dates like "last 7 days" stay
covered). `--force` deletes and reloads each demo customer (this also drops its user mappings).

Usage: uv run python scripts/seed.py [--azure] [--database-url URL] [--days 400] [--force]
"""

import argparse
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/energy-service/src"))
from _common import owner_conninfo  # noqa: E402

from energy_usage_energy.testing.synthetic import CUSTOMERS, SynthCustomer, iter_readings  # noqa: E402

ROLLUP = """
INSERT INTO energy.usage_daily (customer_id, site_id, meter_id, day, kwh)
SELECT r.customer_id, m.site_id, r.meter_id, (r.ts AT TIME ZONE c.timezone)::date, sum(r.kwh)
FROM energy.usage_readings r
JOIN energy.meters m ON m.meter_id = r.meter_id
JOIN energy.customers c ON c.customer_id = r.customer_id
WHERE r.customer_id = %s AND (r.ts AT TIME ZONE c.timezone)::date >= %s
GROUP BY 1, 2, 3, 4
ON CONFLICT (meter_id, day) DO NOTHING
"""


def copy_readings(conn: psycopg.Connection, c: SynthCustomer, start_day: date, end_day: date) -> int:
    n = 0
    with conn.cursor().copy("COPY energy.usage_readings (customer_id, meter_id, ts, kwh) FROM STDIN") as cp:
        for _site_id, meter_id, ts, kwh in iter_readings(c, start_day, end_day):
            cp.write_row((c.customer_id, meter_id, ts, kwh))
            n += 1
    conn.execute(ROLLUP, (c.customer_id, start_day))
    return n


def top_up(conn: psycopg.Connection, c: SynthCustomer, end_day: date) -> bool:
    """Append missing days for an existing customer. Returns False when the customer isn't loaded yet."""
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM energy.customers WHERE customer_id = %s), "
        "(SELECT max(day) FROM energy.usage_daily WHERE customer_id = %s)",
        (c.customer_id, c.customer_id),
    ).fetchone()
    assert row is not None
    exists, last_day = row
    if not exists or last_day is None:
        return False
    if last_day >= end_day:
        print(f"skipped {c.name}: up to date ({last_day})")
        return True
    with conn.transaction():
        n = copy_readings(conn, c, last_day + timedelta(days=1), end_day)
    print(f"topped up {c.name}: {n} readings, {last_day + timedelta(days=1)}..{end_day}")
    return True


def seed(conn: psycopg.Connection, days: int, force: bool = False) -> None:
    end_day = datetime.now(UTC).date() - timedelta(days=1)
    start_day = end_day - timedelta(days=days)
    for c in CUSTOMERS:
        if not force and top_up(conn, c, end_day):
            continue
        with conn.transaction():
            conn.execute("DELETE FROM energy.customers WHERE customer_id = %s", (c.customer_id,))
            conn.execute(
                "INSERT INTO energy.customers (customer_id, name, timezone) VALUES (%s, %s, %s)",
                (c.customer_id, c.name, c.timezone),
            )
            for tid, oid in c.users:
                conn.execute(
                    "INSERT INTO energy.user_customer (tid, oid, customer_id) VALUES (%s, %s, %s) "
                    "ON CONFLICT (tid, oid) DO UPDATE SET customer_id = EXCLUDED.customer_id",
                    (tid, oid, c.customer_id),
                )
            for site in c.sites:
                conn.execute(
                    "INSERT INTO energy.sites (site_id, customer_id, name, city) VALUES (%s, %s, %s, %s)",
                    (site.site_id, c.customer_id, site.name, site.city),
                )
                for m in site.meters:
                    conn.execute(
                        "INSERT INTO energy.meters (meter_id, customer_id, site_id, name, type) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (m.meter_id, c.customer_id, site.site_id, m.name, m.type),
                    )
            n = copy_readings(conn, c, start_day, end_day)
        print(f"seeded {c.name}: {n} readings, {start_day}..{end_day}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--azure", action="store_true")
    parser.add_argument("--database-url")
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--force", action="store_true", help="Delete and reload the demo customers.")
    args = parser.parse_args()
    with psycopg.connect(owner_conninfo(args.azure, args.database_url), autocommit=True) as conn:
        seed(conn, args.days, args.force)


if __name__ == "__main__":
    main()
