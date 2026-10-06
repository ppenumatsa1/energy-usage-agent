import pytest

from energy_usage_app_api.application.errors import UpstreamUnavailable
from energy_usage_app_api.infrastructure.mcp_gateway import McpToolGatewayFactory


async def test_task_group_errors_are_unwrapped() -> None:
    factory = McpToolGatewayFactory("http://energy-service")
    with pytest.raises(UpstreamUnavailable):
        async with factory.open("token", "corr"):
            raise BaseExceptionGroup("tg", [ExceptionGroup("inner", [UpstreamUnavailable("down")])])
