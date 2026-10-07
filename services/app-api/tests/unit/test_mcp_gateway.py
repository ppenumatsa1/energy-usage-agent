from contextlib import AsyncExitStack
from types import SimpleNamespace as NS

import pytest

from energy_usage_app_api.application.errors import UpstreamUnavailable
from energy_usage_app_api.infrastructure.mcp_gateway import McpToolGateway, McpToolGatewayFactory


async def test_task_group_errors_are_unwrapped() -> None:
    factory = McpToolGatewayFactory("http://energy-service")
    with pytest.raises(UpstreamUnavailable):
        async with factory.open("token", "corr"):
            raise BaseExceptionGroup("tg", [ExceptionGroup("inner", [UpstreamUnavailable("down")])])


class _Session:
    def __init__(self, result: object) -> None:
        self.result = result

    async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
        return self.result


def _gateway(result: object) -> McpToolGateway:
    gw = McpToolGateway("http://energy-service/mcp", {}, AsyncExitStack())
    gw._session = _Session(result)  # type: ignore[assignment]
    return gw


@pytest.mark.parametrize(
    "result",
    [
        NS(isError=False, structuredContent=None, content=[NS(text="not json")]),
        NS(isError=False, structuredContent={"rows": "nope"}, content=[]),
        NS(isError=False, structuredContent=None, content=[]),
    ],
)
async def test_unexpected_tool_results_become_tool_errors(result: object) -> None:
    call = await _gateway(result).call("get_usage", {})
    assert call.result is None and call.error is not None and call.error.code == "internal"
