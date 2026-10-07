"""Builds the runtime object graph from settings. Tests pass overrides instead of patching."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from energy_usage_shared.auth import TokenValidator, build_validator

from .application.chat_service import ChatService
from .application.ports import AgentRunner, ConversationStore, OboProvider, ProfileClient, ToolGatewayFactory
from .config import AppApiSettings

_log = logging.getLogger("energy_usage.history")


class RetentionPurger:
    """Runs ChatService.purge_expired in the background: shortly after startup, then every interval.
    Never raises into the app; stop() cancels it cleanly."""

    def __init__(self, chat: ChatService, interval_s: float, first_delay_s: float = 60.0) -> None:
        self._chat = chat
        self._interval_s = interval_s
        self._first_delay_s = min(first_delay_s, interval_s)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="history-retention-purge")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        delay = self._first_delay_s
        while True:
            await asyncio.sleep(delay)
            delay = self._interval_s
            try:
                await self._chat.purge_expired()
            except Exception:
                _log.exception("history_purge_failed", extra={"event": "history_purge_failed"})


@dataclass
class Container:
    settings: AppApiSettings
    chat: ChatService
    validator: TokenValidator
    startup: list[Callable[[], Awaitable[Any]]] = field(default_factory=list)
    shutdown: list[Callable[[], Awaitable[Any]]] = field(default_factory=list)


def build_container(
    settings: AppApiSettings,
    *,
    validator: TokenValidator | None = None,
    agent: AgentRunner | None = None,
    tools: ToolGatewayFactory | None = None,
    obo: OboProvider | None = None,
    profile: ProfileClient | None = None,
    conversations: ConversationStore | None = None,
) -> Container:
    from .infrastructure.ratelimit import SlidingWindowLimiter

    startup: list[Callable[[], Awaitable[Any]]] = []
    shutdown: list[Callable[[], Awaitable[Any]]] = []

    if agent is None:
        if settings.agent_mode == "fake":
            from .testing.fake_agent import FakeAgentRunner

            agent = FakeAgentRunner()
        else:
            from .orchestration.foundry import FoundryAgentRunner

            assert settings.foundry_project_endpoint
            runner = FoundryAgentRunner.connect(
                settings.foundry_project_endpoint,
                settings.foundry_agent_name,
                settings.agent_max_rounds,
                settings.azure_client_id,
            )
            shutdown.append(runner.aclose)
            agent = runner

    if tools is None:
        from .infrastructure.mcp_gateway import McpToolGatewayFactory

        tools = McpToolGatewayFactory(settings.energy_service_url)

    if obo is None:
        from .infrastructure.obo import DevOboProvider, EntraOboProvider

        if settings.obo_credential == "dev":
            assert settings.dev_jwt_secret
            obo = DevOboProvider(
                settings.dev_jwt_secret, settings.energy_service_audience, settings.energy_service_scope
            )
        else:
            assert settings.entra_client_id
            obo = EntraOboProvider(
                settings.entra_client_id,
                settings.auth_tenant_id,
                settings.energy_service_scope,
                secret=settings.obo_client_secret if settings.obo_credential == "secret" else None,
                mi_client_id=settings.azure_client_id,
            )

    if profile is None:
        from .infrastructure.energy_profile import HttpProfileClient

        http_profile = HttpProfileClient(settings.energy_service_url)
        shutdown.append(http_profile.aclose)
        profile = http_profile

    store_kind = "custom" if conversations is not None else "memory"
    if conversations is None:
        if settings.app_database_url or settings.app_db_host:
            from energy_usage_shared.db import build_pool

            from .infrastructure.conversations_pg import PgConversationStore

            pool = build_pool(
                database_url=settings.app_database_url,
                host=settings.app_db_host,
                dbname=settings.app_db_name,
                user=settings.app_db_user,
                entra_auth=settings.app_db_entra_auth,
                client_id=settings.azure_client_id,
            )
            startup.append(lambda: pool.open(wait=False))
            shutdown.append(pool.close)
            conversations = PgConversationStore(pool)
            store_kind = "postgres"
        else:
            from .testing.memory import MemoryConversationStore

            conversations = MemoryConversationStore()

    chat = ChatService(
        agent=agent,
        tools=tools,
        obo=obo,
        profile=profile,
        conversations=conversations,
        limiter=SlidingWindowLimiter(settings.rate_limit_per_minute),
        agent_kind=settings.agent_mode,
        agent_name=settings.foundry_agent_name,
        retention_days=settings.history_retention_days,
        store_kind=store_kind,
        purge_batch_size=settings.history_purge_batch_size,
    )
    if settings.history_purge_interval_minutes > 0:
        purger = RetentionPurger(chat, settings.history_purge_interval_minutes * 60)
        startup.append(purger.start)
        shutdown.append(purger.stop)  # shutdown runs in reverse: stops before the pool closes
    return Container(settings, chat, validator or build_validator(settings), startup, shutdown)
