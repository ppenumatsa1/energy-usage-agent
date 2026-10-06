"""Errors the API maps to problem responses. Codes match the frontend's ProblemCode list."""


class ChatError(Exception):
    status = 500
    code = "internal_error"
    title = "Something went wrong"

    def __init__(self, detail: str | None = None, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.headers = headers or {}


class NotOnboarded(ChatError):
    status, code, title = 403, "not_onboarded", "Account not linked"


class RateLimited(ChatError):
    status, code, title = 429, "rate_limited", "Too many requests"

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Try again in {retry_after} seconds.", {"Retry-After": str(retry_after)})
        self.retry_after = retry_after


class ConversationNotFound(ChatError):
    status, code, title = 404, "conversation_not_found", "Conversation not found"


class UpstreamUnavailable(ChatError):
    status, code, title = 503, "upstream_unavailable", "Service temporarily unavailable"


class AgentLoopLimit(Exception):
    """The agent kept calling tools past the round limit."""
