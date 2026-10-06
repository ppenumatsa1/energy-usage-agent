"""One-time CI/CD setup (Option B): GitHub Actions deploys code with OIDC; infra stays with `azd up`.

  1. `azd pipeline config` (federated, no secrets): creates the pipeline service principal `energy-usage-ci-<env>`
     with a GitHub OIDC credential, Contributor on the subscription, and the GitHub variables AZURE_CLIENT_ID,
     AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID, AZURE_ENV_NAME, AZURE_LOCATION.
  2. Saves its object ID as AZURE_PIPELINE_PRINCIPAL_ID and runs `azd provision`, so Bicep gives it Azure AI User on
     Foundry (the deploy workflow publishes the agent version).

No tenant admin needed: CI never provisions, so it never touches the app registrations.
The workflow is `.github/workflows/azure-dev.yml`, the file name `azd pipeline config` looks for (otherwise it
offers to add its default workflow, which provisions).
Run once from a clone with a GitHub remote, signed in to az, azd and gh: uv run python scripts/setup_ci.py
"""

import json
import os
import subprocess
import sys

from _common import ROOT, azd_env

ENV = {**os.environ, "AZD_SKIP_UPDATE_CHECK": "true"}


def azd(*args: str) -> None:
    print(f"\n$ azd {' '.join(args)}", flush=True)
    if subprocess.run(["azd", *args], cwd=ROOT, env=ENV).returncode != 0:
        sys.exit(f"setup_ci: azd {args[0]} {args[1] if len(args) > 1 else ''} failed")


def object_id(name: str) -> str:
    out = subprocess.run(["az", "ad", "sp", "list", "--display-name", name, "--query", "[].id", "-o", "json"],
                         capture_output=True, text=True, check=True)  # fmt: skip
    ids = json.loads(out.stdout)
    if len(ids) != 1:
        sys.exit(f"setup_ci: expected one service principal named {name}, found {len(ids)}")
    return ids[0]


def main() -> int:
    name = f"energy-usage-ci-{azd_env()['AZURE_ENV_NAME']}"
    print("When azd asks to commit and push, answer No: CI can't publish the agent until step 2 has run.")
    azd("pipeline", "config", "--provider", "github", "--auth-type", "federated",
        "--principal-name", name, "--principal-role", "Contributor")  # fmt: skip
    azd("env", "set", "AZURE_PIPELINE_PRINCIPAL_ID", object_id(name))
    azd("provision", "--no-prompt")
    print(
        "\nCI ready: push to main to start the first run. Every push deploys code and the agent, then verifies. "
        "Infra changes: run `azd up`."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
