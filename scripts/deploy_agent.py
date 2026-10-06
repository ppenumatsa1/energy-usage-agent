"""Create a new version of the Foundry prompt agent from agent/ (azd postdeploy hook).

Skips when the latest version already has the same definition (sha256 stored in version metadata).
Values come from the environment or `azd env get-values`:
  AZURE_AI_PROJECT_ENDPOINT, AZURE_AI_MODEL_DEPLOYMENT_NAME, FOUNDRY_AGENT_NAME (optional override).
`--dry-run` prints the definition without calling Azure; `--force` creates a version even if unchanged.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import azd_env, env_or_azd  # noqa: E402

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"


def _expand(value: str, env: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        resolved = env_or_azd(name, env)
        if not resolved:
            raise SystemExit(f"{name} is not set (environment or azd env).")
        return resolved

    return re.sub(r"\$\{([A-Z0-9_]+)\}", sub, value)


def load_definition(env: dict[str, str]) -> dict[str, Any]:
    spec = yaml.safe_load((AGENT_DIR / "agent.yaml").read_text())
    tools = [json.loads(p.read_text()) for p in sorted((AGENT_DIR / spec["tools"]).glob("*.json"))]
    if not tools:
        raise SystemExit("agent/tools is empty. Run: uv run python scripts/sync_tool_specs.py")
    fmt = spec["response_format"]
    return {
        "name": env_or_azd("FOUNDRY_AGENT_NAME", env, spec["name"]),
        "description": spec.get("description", ""),
        "model": _expand(str(spec["model"]), env),
        "temperature": spec.get("temperature"),
        "instructions": (AGENT_DIR / spec["instructions"]).read_text(),
        "tools": tools,
        "response_format": {
            "name": fmt["name"],
            "schema": json.loads((AGENT_DIR / fmt["schema"]).read_text()),
            "strict": bool(fmt.get("strict", True)),
        },
    }


def definition_sha(d: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def latest_version(project: Any, name: str) -> dict[str, Any] | None:
    from azure.core.exceptions import ResourceNotFoundError

    try:
        return dict(project.agents.get(name)["versions"]["latest"])
    except ResourceNotFoundError:
        return None


def deploy(d: dict[str, Any], endpoint: str, force: bool = False) -> None:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import (
        FunctionTool,
        PromptAgentDefinition,
        PromptAgentDefinitionTextOptions,
        TextResponseFormatJsonSchema,
    )
    from azure.identity import DefaultAzureCredential

    optional = {"temperature": d["temperature"]} if d["temperature"] is not None else {}
    definition = PromptAgentDefinition(
        model=d["model"],
        instructions=d["instructions"],
        **optional,
        # strict=False: tool schemas have optional parameters, which strict mode does not allow.
        tools=[FunctionTool(name=t["name"], description=t["description"], parameters=t["parameters"], strict=False)
               for t in d["tools"]],
        text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(**d["response_format"])),
    )  # fmt: skip
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=endpoint, credential=credential) as project,
    ):
        sha = definition_sha(d)
        latest = latest_version(project, d["name"])
        if not force and latest and (latest.get("metadata") or {}).get("definition_sha") == sha:
            print(f"Agent {d['name']} unchanged (version {latest['version']}); skipped.")
            return
        version = project.agents.create_version(
            agent_name=d["name"],
            definition=definition,
            description=d["description"],
            metadata={"definition_sha": sha},
        )
    print(f"Deployed agent {d['name']} version {version.version}.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="create a version even if unchanged")
    args = parser.parse_args()
    env = azd_env()
    d = load_definition(env)
    if args.dry_run:
        print(json.dumps({**d, "instructions": f"<{len(d['instructions'])} chars>"}, indent=2)[:4000])
        return 0
    endpoint = env_or_azd("AZURE_AI_PROJECT_ENDPOINT", env)
    if not endpoint:
        raise SystemExit("AZURE_AI_PROJECT_ENDPOINT is not set (environment or azd env).")
    deploy(d, endpoint, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
