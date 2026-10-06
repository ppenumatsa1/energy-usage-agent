"""Cross-component contracts: interfaces never take identity, the agent definition matches the code."""

import json
import re
import typing
from pathlib import Path

import pytest
import yaml

from energy_usage_shared.contracts import AgentOutput, ChartSpec

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agent"
FORBIDDEN = {"customer_id", "customerid", "tenant_id", "tenantid", "tid", "oid", "user_id"}


def _keys(schema: object) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        for k, v in schema.items():
            if k == "properties" and isinstance(v, dict):
                found |= {p.lower() for p in v}
            found |= _keys(v)
    elif isinstance(schema, list):
        for v in schema:
            found |= _keys(v)
    return found


def test_agent_tools_match_mcp_tools_list() -> None:
    from energy_usage_energy.mcp.specs import tool_specs

    on_disk = {p.stem: json.loads(p.read_text()) for p in (AGENT / "tools").glob("*.json")}
    assert on_disk == {s["name"]: s for s in tool_specs()}, "run: uv run python scripts/sync_tool_specs.py"


def test_no_identity_parameters_in_mcp_or_agent_tools() -> None:
    for spec in (json.loads(p.read_text()) for p in (AGENT / "tools").glob("*.json")):
        assert not (_keys(spec["parameters"]) & FORBIDDEN), spec["name"]


@pytest.mark.parametrize("module", ["energy_usage_energy.main", "energy_usage_app_api.main"])
def test_no_identity_parameters_in_rest(module: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from fastapi.openapi.utils import get_openapi

    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("DEV_JWT_SECRET", "x" * 40)
    monkeypatch.setenv("REPOSITORY", "memory")
    monkeypatch.setenv("AGENT_MODE", "fake")
    monkeypatch.setenv("OBO_CREDENTIAL", "dev")
    app = importlib.import_module(module).create_app()
    spec = get_openapi(title="t", version="0", routes=app.routes)
    for path, ops in spec["paths"].items():
        assert not (set(re.findall(r"{(\w+)}", path.lower())) & FORBIDDEN), path
        for op in ops.values():
            names = {p["name"].lower() for p in op.get("parameters", [])}
            assert not (names & FORBIDDEN), f"{path}: {names & FORBIDDEN}"
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        if name.endswith("Request"):
            assert not (_keys(schema) & FORBIDDEN), name


def test_output_schema_matches_agent_output_model() -> None:
    schema = json.loads((AGENT / "output-schema.json").read_text())
    assert set(schema["properties"]) == set(AgentOutput.model_fields)
    assert set(schema["required"]) == set(schema["properties"])  # strict structured output
    statuses = typing.get_args(AgentOutput.model_fields["status"].annotation)
    assert schema["properties"]["status"]["enum"] == list(statuses)
    chart = next(s for s in schema["properties"]["chart"]["anyOf"] if s.get("type") == "object")
    assert set(chart["properties"]) == set(ChartSpec.model_fields)
    sample = {"answer": "a", "status": "ok", "chart": {"type": "bar", "x": "period", "y": ["kwh"], "series": None,
              "title": ""}, "result_ids": ["r_1"]}  # fmt: skip
    import jsonschema

    jsonschema.validate(sample, schema)
    AgentOutput.model_validate(sample)


def test_agent_yaml_references_exist() -> None:
    spec = yaml.safe_load((AGENT / "agent.yaml").read_text())
    assert (AGENT / spec["instructions"]).is_file()
    assert (AGENT / spec["response_format"]["schema"]).is_file()
    assert "${" in str(spec["model"]), "model must come from the environment"


def test_golden_dataset_uses_known_tools() -> None:
    names = {p.stem for p in (AGENT / "tools").glob("*.json")}
    for line in (AGENT / "evals/datasets/golden.jsonl").read_text().splitlines():
        row = json.loads(line)
        assert set(row["expected_tools"]) <= names, row


def test_golden_smoke_rows_cover_answer_clarify_and_refuse() -> None:
    rows = [json.loads(line) for line in (AGENT / "evals/datasets/golden.jsonl").read_text().splitlines()]
    smoke = [r for r in rows if "smoke" in r.get("tags", [])]
    assert {r["expected_status"] for r in smoke} >= {"ok", "clarify", "refused"}
    spec = yaml.safe_load((AGENT / "eval.yaml").read_text())
    for pattern in spec["policy"]["full_when_changed"]:
        assert list(ROOT.glob(pattern)), f"policy pattern matches nothing: {pattern}"


def test_frontend_calls_only_the_same_origin_api() -> None:
    src = ROOT / "frontend/src"
    for f in [*src.rglob("*.ts"), *src.rglob("*.tsx")]:
        text = f.read_text()
        for url in re.findall(r"https?://[^\s\"'`]+", text):
            assert "login.microsoftonline.com" in url or "localhost" in url, f"{f}: {url}"
