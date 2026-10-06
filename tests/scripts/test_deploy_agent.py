import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture
def deploy_agent(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("deploy_agent_under_test", SCRIPTS / "deploy_agent.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DEFINITION: dict[str, Any] = {
    "name": "agent",
    "description": "d",
    "model": "m",
    "temperature": None,
    "instructions": "be brief",
    "tools": [{"name": "get_usage", "description": "x", "parameters": {"type": "object"}}],
    "response_format": {"name": "out", "schema": {"type": "object"}, "strict": True},
}


def test_definition_sha_is_stable_and_detects_changes(deploy_agent) -> None:  # type: ignore[no-untyped-def]
    reordered = dict(reversed(list(DEFINITION.items())))
    assert deploy_agent.definition_sha(DEFINITION) == deploy_agent.definition_sha(reordered)
    assert deploy_agent.definition_sha(DEFINITION) != deploy_agent.definition_sha(
        {**DEFINITION, "instructions": "be very brief"}
    )


class FakeAgents:
    def __init__(self, latest: dict[str, Any] | None) -> None:
        self.latest = latest
        self.created: list[dict[str, Any]] = []

    def get(self, name: str) -> dict[str, Any]:
        from azure.core.exceptions import ResourceNotFoundError

        if self.latest is None:
            raise ResourceNotFoundError("missing")
        return {"versions": {"latest": self.latest}}

    def create_version(self, **kwargs: Any) -> SimpleNamespace:
        self.created.append(kwargs)
        return SimpleNamespace(version=str(len(self.created) + 1))


@pytest.mark.parametrize(
    ("latest", "force", "creates"),
    [
        (None, False, True),
        ({"version": "4", "metadata": {}}, False, True),
        ({"version": "4", "metadata": {"definition_sha": "SAME"}}, False, False),
        ({"version": "4", "metadata": {"definition_sha": "SAME"}}, True, True),
    ],
)
def test_deploy_skips_only_when_unchanged(deploy_agent, monkeypatch, latest, force, creates) -> None:  # type: ignore[no-untyped-def]
    import azure.ai.projects
    import azure.identity

    sha = deploy_agent.definition_sha(DEFINITION)
    if latest and latest["metadata"].get("definition_sha") == "SAME":
        latest["metadata"]["definition_sha"] = sha
    agents = FakeAgents(latest)

    class Client:
        def __init__(self, **_: Any) -> None:
            self.agents = agents

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

    monkeypatch.setattr(azure.ai.projects, "AIProjectClient", Client)
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", Client)
    deploy_agent.deploy(DEFINITION, "https://example.invalid", force=force)
    assert bool(agents.created) is creates
    if creates:
        assert agents.created[0]["metadata"] == {"definition_sha": sha}
