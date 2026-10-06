"""Helpers for scripts. Connection details come from flags or env (azd env in Azure); nothing is hardcoded."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_STATE = ROOT / ".local"
ENTRA_DB_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def azd_env() -> dict[str, str]:
    """Values from `azd env get-values` (empty if azd is not set up)."""
    try:
        out = subprocess.run(
            ["azd", "env", "get-values", "--output", "json"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        ).stdout
        return {k: str(v) for k, v in json.loads(out).items()}
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return {}


def env_or_azd(name: str, azd: dict[str, str], default: str | None = None) -> str | None:
    return os.environ.get(name) or azd.get(name) or default


def owner_conninfo(azure: bool, database_url: str | None, dbname: str | None = None) -> str:
    """Connection string for the schema owner (migrations / seed). `dbname` overrides the Azure database."""
    import psycopg

    if not azure:
        url = database_url or os.environ.get("MIGRATE_DATABASE_URL") or _local_url()
        if not url:
            sys.exit(
                "Set --database-url or MIGRATE_DATABASE_URL, or start a local DB: uv run python scripts/local_db.py"
            )
        return url
    from azure.identity import DefaultAzureCredential

    azd = azd_env()
    host = env_or_azd("POSTGRES_HOST", azd)
    dbname = dbname or env_or_azd("POSTGRES_DATABASE", azd, "energy")
    user = env_or_azd("POSTGRES_ADMIN_USER", azd) or _signed_in_user()
    if not host or not user:
        sys.exit("POSTGRES_HOST (azd output) and POSTGRES_ADMIN_USER (or an az login) are required")
    token = DefaultAzureCredential().get_token(ENTRA_DB_SCOPE).token
    return psycopg.conninfo.make_conninfo(
        host=host, dbname=dbname, user=user, password=token, sslmode="require"
    )


def _signed_in_user() -> str | None:
    try:
        return subprocess.run(
            ["az", "account", "show", "--query", "user.name", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _local_url() -> str | None:
    f = LOCAL_STATE / "database_url"
    return f.read_text().strip() if f.exists() else None
