import pytest
from pydantic import ValidationError

from energy_usage_app_api.config import AppApiSettings


def test_fake_and_dev_are_forbidden_in_azure() -> None:
    with pytest.raises(ValidationError):
        AppApiSettings(environment="azure", auth_mode="entra", agent_mode="fake", entra_client_id="x")
    with pytest.raises(ValidationError):
        AppApiSettings(
            environment="azure", auth_mode="dev", dev_jwt_secret="x" * 40, obo_credential="dev",
            foundry_project_endpoint="https://example.invalid",
        )  # fmt: skip


def test_foundry_needs_endpoint() -> None:
    with pytest.raises(ValidationError):
        AppApiSettings(environment="local", auth_mode="entra", agent_mode="foundry", entra_client_id="x")
