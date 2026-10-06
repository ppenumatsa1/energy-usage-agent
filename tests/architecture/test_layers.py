"""Import rules that keep the layers honest (see docs/project-structure.md)."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "services/app-api/src/energy_usage_app_api"
ENERGY = ROOT / "services/energy-service/src/energy_usage_energy"

FRAMEWORKS = {"fastapi", "starlette", "sse_starlette", "mcp", "azure", "openai", "psycopg", "psycopg_pool",
              "httpx", "msal", "uvicorn"}  # fmt: skip


def imports(path: Path) -> set[str]:
    """Absolute top-level modules plus relative imports resolved to the package's first-level layer."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module)
            elif node.level:
                found.add("." * node.level + (node.module or ""))
    return found


def files(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.py"))


def top(names: set[str]) -> set[str]:
    return {n.split(".")[0] for n in names if not n.startswith(".")}


@pytest.mark.parametrize("path", files(APP / "application") + files(APP / "projections") + files(ENERGY / "application"),
                         ids=lambda p: str(p.relative_to(ROOT)))  # fmt: skip
def test_core_is_framework_free(path: Path) -> None:
    names = imports(path)
    assert not (top(names) & FRAMEWORKS), f"{path.name} imports {top(names) & FRAMEWORKS}"
    layers = {n.lstrip(".").split(".")[0] for n in names if n.startswith("..")}
    assert not (layers & {"api", "mcp", "infrastructure", "orchestration", "testing", "bootstrap"})


def test_only_orchestration_talks_to_foundry() -> None:
    for path in files(APP):
        uses = {n for n in imports(path) if n.startswith(("azure.ai", "openai"))}
        if uses:
            assert path.parent.name == "orchestration", f"{path} imports {uses}"


def test_only_infrastructure_touches_the_database() -> None:
    allowed = {ENERGY / "infrastructure", APP / "infrastructure"}
    for path in files(APP) + files(ENERGY):
        if top(imports(path)) & {"psycopg", "psycopg_pool"} and path.name != "bootstrap.py":
            assert path.parent in allowed, f"{path} imports psycopg"


def test_energy_sql_runs_inside_the_customer_scope() -> None:
    """Usage queries run only on a PgUsageReader, and a reader is only ever built from rls_session(),
    which sets app.customer_id for the transaction. Pool connections are used only for the mapping
    lookup (SECURITY DEFINER function) and the health ping."""
    tree = ast.parse((ENERGY / "infrastructure/postgres.py").read_text())
    pool_users: set[str] = set()
    reader_builders: set[str] = set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]:
        body = ast.unparse(fn)
        if "_pool.connection(" in body or "pool.connection(" in body:
            pool_users.add(fn.name)
        if "PgUsageReader(" in body:
            reader_builders.add(fn.name)
            assert "rls_session(" in body
    assert pool_users == {"resolve", "ping", "rls_session"}
    assert reader_builders == {"scoped"}
    reader = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PgUsageReader")
    assert "_pool" not in ast.unparse(reader)
    for module in files(ENERGY):
        if module.name != "postgres.py":
            assert "PgUsageReader(" not in module.read_text(), module
