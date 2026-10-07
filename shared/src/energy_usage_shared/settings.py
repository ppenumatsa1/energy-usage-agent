"""Settings common to every service. Values come from environment variables only."""

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    environment: Literal["local", "test", "azure"] = "local"
    log_level: str = "INFO"
    applicationinsights_connection_string: str | None = None

    auth_mode: Literal["entra", "dev"] = "entra"
    auth_audience: str = ""
    auth_tenant_id: str = ""  # the home tenant; external users are B2B guests in it
    auth_required_scope: str = ""
    # Comma-separated client (app) IDs allowed to call this API (token `azp`/`appid`). Required for Entra auth.
    auth_allowed_client_ids: str = ""
    dev_jwt_secret: str | None = None

    @model_validator(mode="after")
    def _guard_dev_auth(self) -> "ServiceSettings":
        if self.auth_mode == "dev":
            if self.environment == "azure":
                raise ValueError("AUTH_MODE=dev is not allowed when ENVIRONMENT=azure")
            if not self.dev_jwt_secret or len(self.dev_jwt_secret) < 32:
                raise ValueError("AUTH_MODE=dev requires DEV_JWT_SECRET with at least 32 characters")
        return self
