"""Apply SQL migrations for both services, then grant the app login roles.

Local:  uv run python scripts/migrate.py [--database-url URL]
Azure:  uv run python scripts/migrate.py --azure   (needs the client-IP firewall rule and you as Entra admin)
"""

import argparse
import os
from pathlib import Path

import psycopg
from _common import ROOT, azd_env, env_or_azd, owner_conninfo
from psycopg import sql

SERVICES = [
    ("energy-service", ROOT / "services/energy-service/migrations", "energy_reader"),
    ("app-api", ROOT / "services/app-api/migrations", "app_api_rw"),
]
LOCAL_LOGINS = {"energy-service": "energy_app", "app-api": "app_api_app"}
AZURE_LOGIN_VARS = {"energy-service": "ENERGY_SERVICE_IDENTITY_NAME", "app-api": "APP_API_IDENTITY_NAME"}


def apply_migrations(conn: psycopg.Connection, service: str, folder: Path) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS public.schema_migrations "
        "(service text, version text, applied_at timestamptz DEFAULT now(), PRIMARY KEY (service, version))"
    )
    done = {
        r[0]
        for r in conn.execute("SELECT version FROM public.schema_migrations WHERE service=%s", (service,))
    }
    for path in sorted(folder.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text())  # type: ignore[arg-type]
            conn.execute(
                "INSERT INTO public.schema_migrations (service, version) VALUES (%s, %s)",
                (service, path.name),
            )
        print(f"applied {service}/{path.name}")


def role_exists(conn: psycopg.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)).fetchone() is not None


def grant_local(conn: psycopg.Connection, login: str, group: str) -> None:
    password = os.environ.get("LOCAL_DB_APP_PASSWORD", "local-dev-only")
    if not role_exists(conn, login):
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(login), sql.Literal(password))
        )
    conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(login)))
    print(f"granted {group} to local login {login}")


def create_azure_principals(names: list[str]) -> None:
    """Entra login roles are server-wide but can only be created from the `postgres` database."""
    with psycopg.connect(owner_conninfo(True, None, dbname="postgres"), autocommit=True) as conn:
        for name in names:
            if not role_exists(conn, name):
                conn.execute("SELECT * FROM pgaadauth_create_principal(%s, false, false)", (name,))
                print(f"created Entra login role {name}")


def grant_azure(conn: psycopg.Connection, identity_name: str, group: str) -> None:
    conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(identity_name)))
    print(f"granted {group} to managed identity {identity_name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--azure", action="store_true")
    parser.add_argument("--database-url")
    args = parser.parse_args()
    azd = azd_env() if args.azure else {}
    if args.azure:
        create_azure_principals([n for v in AZURE_LOGIN_VARS.values() if (n := env_or_azd(v, azd))])
    with psycopg.connect(owner_conninfo(args.azure, args.database_url), autocommit=True) as conn:
        for service, folder, group in SERVICES:
            apply_migrations(conn, service, folder)
            if args.azure:
                name = env_or_azd(AZURE_LOGIN_VARS[service], azd)
                if name:
                    grant_azure(conn, name, group)
                else:
                    print(f"skip grant: {AZURE_LOGIN_VARS[service]} not set")
            else:
                grant_local(conn, LOCAL_LOGINS[service], group)


if __name__ == "__main__":
    main()
