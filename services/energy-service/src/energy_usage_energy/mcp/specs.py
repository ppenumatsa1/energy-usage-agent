"""MCP `tools/list` as plain function-tool specs (refs inlined, titles stripped) for the Foundry agent."""

import asyncio
from datetime import date
from typing import Any


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
        return {k: _inline(v, defs) for k, v in node.items() if k not in ("title", "$defs")}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


async def _list() -> list[dict[str, Any]]:
    from ..application.service import UsageService
    from ..testing.memory import MemoryDirectory, MemoryRepository
    from .server import build_mcp

    mcp = build_mcp(UsageService(MemoryDirectory(), MemoryRepository(end_day=date(2000, 1, 1))))
    specs = []
    for tool in await mcp.list_tools():
        schema = dict(tool.inputSchema)
        params = _inline(schema, schema.get("$defs", {}))
        params.setdefault("additionalProperties", False)
        specs.append({"name": tool.name, "description": tool.description or "", "parameters": params})
    return sorted(specs, key=lambda s: s["name"])


def tool_specs() -> list[dict[str, Any]]:
    return asyncio.run(_list())
