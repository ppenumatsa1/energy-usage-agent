"""Real Postgres for RLS tests: TEST_DATABASE_URL (CI service container) or an embedded pgserver."""

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import conninfo, sql

from energy_usage_energy.testing.synthetic import CUSTOMERS, iter_readings

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
LOGIN = "energy_it_login"
LOGIN_PASSWORD = "it-only-password"  # noqa: S105 - throwaway role in a throwaway database
SEED_DAYS = 40


@pytest.fixture(scope="session")
def admin_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pg")), cleanup_mode="stop")
    try:
        yield server.get_uri()
    finally:
        server.cleanup()


@pytest.fixture(scope="session")
def database(admin_url: str) -> Iterator[dict[str, str]]:
    """Fresh database with migrations + a small synthetic seed. Yields owner and app-login URLs."""
    name = f"energy_it_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(admin_url, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo.conninfo_to_dict(admin_url)
    owner_url = conninfo.make_conninfo(**{**params, "dbname": name})
    with psycopg.connect(owner_url, autocommit=True) as c:
        for f in sorted(MIGRATIONS.glob("*.sql")):
            c.execute(f.read_text())  # type: ignore[arg-type]
        if not c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (LOGIN,)).fetchone():
            c.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(LOGIN), sql.Literal(LOGIN_PASSWORD)
                )
            )
        c.execute(sql.SQL("GRANT energy_reader TO {}").format(sql.Identifier(LOGIN)))
        _seed(c)
    app_url = conninfo.make_conninfo(**{**params, "dbname": name, "user": LOGIN, "password": LOGIN_PASSWORD})
    yield {"owner": owner_url, "app": app_url}
    with psycopg.connect(admin_url, autocommit=True) as c:
        c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _seed(c: psycopg.Connection) -> None:
    end = datetime.now(UTC).date() - timedelta(days=1)
    start = end - timedelta(days=SEED_DAYS)
    for cust in CUSTOMERS:
        c.execute(
            "INSERT INTO energy.customers VALUES (%s, %s, %s)", (cust.customer_id, cust.name, cust.timezone)
        )
        for tid, oid in cust.users:
            c.execute(
                "INSERT INTO energy.user_customer (tid, oid, customer_id) VALUES (%s, %s, %s)",
                (tid, oid, cust.customer_id),
            )
        for site in cust.sites:
            c.execute(
                "INSERT INTO energy.sites VALUES (%s, %s, %s, %s)",
                (site.site_id, cust.customer_id, site.name, site.city),
            )
            for m in site.meters:
                c.execute(
                    "INSERT INTO energy.meters VALUES (%s, %s, %s, %s, %s)",
                    (m.meter_id, cust.customer_id, site.site_id, m.name, m.type),
                )
        with c.cursor().copy("COPY energy.usage_readings (customer_id, meter_id, ts, kwh) FROM STDIN") as cp:
            for _s, meter_id, ts, kwh in iter_readings(cust, start, end, step_minutes=60):
                cp.write_row((cust.customer_id, meter_id, ts, kwh))
    c.execute(
        """INSERT INTO energy.usage_daily
           SELECT r.customer_id, m.site_id, r.meter_id, (r.ts AT TIME ZONE cu.timezone)::date, sum(r.kwh)
           FROM energy.usage_readings r JOIN energy.meters m USING (meter_id)
           JOIN energy.customers cu ON cu.customer_id = r.customer_id GROUP BY 1, 2, 3, 4"""
    )
