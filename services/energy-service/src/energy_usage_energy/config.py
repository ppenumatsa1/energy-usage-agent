from typing import Literal

from pydantic import model_validator

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

    @model_validator(mode="after")
    def _guard_memory(self) -> "EnergySettings":
        if self.repository == "memory" and self.environment == "azure":
            raise ValueError("REPOSITORY=memory is not allowed when ENVIRONMENT=azure")
        return self
