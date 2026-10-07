from typing import Literal

from pydantic import Field, model_validator

from energy_usage_shared.settings import ServiceSettings


class EnergySettings(ServiceSettings):
    auth_required_scope: str = "Energy.Read"

    repository: Literal["postgres", "memory"] = "postgres"
    database_url: str | None = None
    db_host: str | None = None
    db_name: str | None = None
    db_user: str | None = None
    db_entra_auth: bool = False
    azure_client_id: str | None = None
    db_connect_timeout_seconds: int = Field(default=10, ge=1)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    db_statement_timeout_ms: int = Field(default=10_000, ge=100)

    @model_validator(mode="after")
    def _guard_memory(self) -> "EnergySettings":
        if self.repository == "memory" and self.environment == "azure":
            raise ValueError("REPOSITORY=memory is not allowed when ENVIRONMENT=azure")
        return self
