"""Builds the runtime object graph. Nothing here runs at import time."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg_pool import AsyncConnectionPool

from energy_usage_shared.auth import TokenValidator, build_validator

from .application.ports import CustomerDirectory, UsageRepository
from .application.service import UsageService
from .config import EnergySettings


@dataclass
class Container:
    settings: EnergySettings
    service: UsageService
    repository: UsageRepository
    validator: TokenValidator
    pool: AsyncConnectionPool | None = None


def build_container(settings: EnergySettings, validator: TokenValidator | None = None) -> Container:
    pool: AsyncConnectionPool | None = None
    directory: CustomerDirectory
    repository: UsageRepository
    if settings.repository == "memory":
        from .testing.memory import MemoryDirectory, MemoryRepository

        directory = MemoryDirectory()
        repository = MemoryRepository(end_day=datetime.now(UTC).date() - timedelta(days=1))
    else:
        from energy_usage_shared.db import build_pool

        from .infrastructure.postgres import PgCustomerDirectory, PgUsageRepository

        pool = build_pool(
            database_url=settings.database_url,
            host=settings.db_host,
            dbname=settings.db_name,
            user=settings.db_user,
            entra_auth=settings.db_entra_auth,
            client_id=settings.azure_client_id,
        )
        directory, repository = PgCustomerDirectory(pool), PgUsageRepository(pool)
    return Container(
        settings=settings,
        service=UsageService(directory, repository),
        repository=repository,
        validator=validator or build_validator(settings),
        pool=pool,
    )
