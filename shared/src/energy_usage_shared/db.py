"""Postgres pool shared by both services. Locally: a URL. In Azure: Entra token (managed identity) as password."""

from typing import Any

import psycopg
from psycopg_pool import AsyncConnectionPool

ENTRA_DB_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def entra_connection_class(client_id: str | None) -> type[psycopg.AsyncConnection[Any]]:
    from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential

    credential = ManagedIdentityCredential(client_id=client_id) if client_id else DefaultAzureCredential()

    class EntraAsyncConnection(psycopg.AsyncConnection[Any]):
        @classmethod
        async def connect(cls, conninfo: str = "", **kwargs: Any):  # type: ignore[override]
            token = await credential.get_token(ENTRA_DB_SCOPE)
            kwargs["password"] = token.token
            return await super().connect(conninfo, **kwargs)

    return EntraAsyncConnection


def build_pool(
    *,
    database_url: str | None,
    host: str | None,
    dbname: str | None,
    user: str | None,
    entra_auth: bool,
    client_id: str | None,
    min_size: int = 1,
    max_size: int = 10,
) -> AsyncConnectionPool:
    if database_url:
        return AsyncConnectionPool(database_url, min_size=min_size, max_size=max_size, open=False)
    if not (host and dbname and user):
        raise ValueError("Set DATABASE_URL, or DB_HOST + DB_NAME + DB_USER")
    conninfo = psycopg.conninfo.make_conninfo(host=host, dbname=dbname, user=user, sslmode="require")
    return AsyncConnectionPool(
        conninfo,
        connection_class=entra_connection_class(client_id) if entra_auth else psycopg.AsyncConnection,
        min_size=min_size,
        max_size=max_size,
        max_lifetime=45 * 60,  # Entra tokens last ~60-90 min; recycle connections before expiry
        open=False,
    )
