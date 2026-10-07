class EnergyError(Exception):
    status = 400
    code = "invalid_argument"
    title = "Invalid argument"
    # MCP tool error code (must be one of shared ToolError codes); defaults to `code`.
    tool_code: str | None = None

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    @property
    def mcp_code(self) -> str:
        return self.tool_code or self.code


class InvalidRange(EnergyError):
    code = "invalid_range"
    title = "Invalid date range"


class InvalidArgument(EnergyError):
    code = "invalid_argument"
    title = "Invalid argument"


class NoData(EnergyError):
    status = 404
    code = "no_data"
    title = "No data"


class NotOnboarded(EnergyError):
    status = 403
    code = "not_onboarded"
    title = "Not onboarded"


class DataUnavailable(EnergyError):
    """The data store can't be reached right now (connection, pool or credential failure). Retryable."""

    status = 503
    code = "upstream_unavailable"
    title = "Service temporarily unavailable"
    tool_code = "internal"

    def __init__(
        self, message: str = "Energy data is temporarily unavailable. Try again in a moment."
    ) -> None:
        super().__init__(message)


class QueryTimeout(DataUnavailable):
    """A query hit the statement timeout."""

    def __init__(
        self, message: str = "The query took too long. Try a shorter period or a coarser granularity."
    ) -> None:
        super().__init__(message)
