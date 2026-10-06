from typing import Literal

from pydantic import model_validator

from energy_usage_shared.settings import ServiceSettings


class AppApiSettings(ServiceSettings):
    auth_required_scope: str = "Chat.Ask"

    # Downstream energy-service
    energy_service_url: str = "http://localhost:8001"
    energy_service_scope: str = "Energy.Read"
    energy_service_audience: str = "energy-service"  # dev mode only (audience of minted tokens)

    # On-behalf-of: federated = managed identity as client assertion; secret = client secret; dev = HS256 mint
    entra_client_id: str | None = None
    obo_credential: Literal["federated", "secret", "dev"] = "federated"
    obo_client_secret: str | None = None
    azure_client_id: str | None = None

    # Agent
    agent_mode: Literal["foundry", "fake"] = "foundry"
    foundry_project_endpoint: str | None = None
    foundry_agent_name: str = "energy-usage-agent"
    agent_max_rounds: int = 5

    # Conversation store (none set -> in-memory)
    app_database_url: str | None = None
    app_db_host: str | None = None
    app_db_name: str | None = None
    app_db_user: str | None = None
    app_db_entra_auth: bool = False
    history_retention_days: int = 30

    rate_limit_per_minute: int = 20

    @model_validator(mode="after")
    def _check(self) -> "AppApiSettings":
        azure = self.environment == "azure"
        if azure and (self.agent_mode == "fake" or self.obo_credential == "dev"):
            raise ValueError("AGENT_MODE=fake and OBO_CREDENTIAL=dev are not allowed when ENVIRONMENT=azure")
        if self.agent_mode == "foundry" and not self.foundry_project_endpoint:
            raise ValueError("FOUNDRY_PROJECT_ENDPOINT is required when AGENT_MODE=foundry")
        if self.obo_credential != "dev" and not self.entra_client_id:
            raise ValueError("ENTRA_CLIENT_ID is required for OBO")
        if self.obo_credential == "secret" and not self.obo_client_secret:
            raise ValueError("OBO_CLIENT_SECRET is required when OBO_CREDENTIAL=secret")
        if self.obo_credential == "dev" and self.auth_mode != "dev":
            raise ValueError("OBO_CREDENTIAL=dev requires AUTH_MODE=dev")
        return self
