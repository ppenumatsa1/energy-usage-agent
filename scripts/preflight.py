"""Preprovision hook: check prerequisites and fill the azd env values that used to be set by hand.

Sets AZURE_PRINCIPAL_NAME, AZURE_PRINCIPAL_TYPE (the deployer, from `az login`) and CLIENT_IP_ADDRESS (Postgres
firewall rule for migrate/seed). Fails early, with the fix, when:
  - the deployer is a service principal: provisioning is done by a person (`azd up`); CI only deploys code,
  - the deployer can't create or update app registrations (they are created by infra/modules/entra.bicep), or
  - the model quota in the Foundry region is too small for a first deployment.

Runs automatically before `azd provision` / `azd up`. Manual: uv run python scripts/preflight.py
"""

import json
import subprocess
import sys
from typing import Any

import httpx
from _common import ROOT, azd_env, env_or_azd

GRAPH = "https://graph.microsoft.com/v1.0"
# Directory roles that can create app registrations even when users can't.
APP_ADMIN_ROLE_TEMPLATES = {
    "62e90394-69f5-4237-9190-012177145e10": "Global Administrator",
    "9b895d92-2cd3-44c7-9d02-a6ac2d5ea5c3": "Application Administrator",
    "158c047a-c907-4556-b7ef-446551a6b5f7": "Cloud Application Administrator",
    "cf1c38e5-3621-4004-a7cb-879624dced7c": "Application Developer",
}


def az(*args: str, check: bool = True) -> Any:
    out = subprocess.run(["az", *args, "-o", "json"], capture_output=True, text=True)
    if out.returncode != 0:
        if check:
            sys.exit(f"preflight: az {' '.join(args[:3])} failed: {out.stderr.strip()[:300]}")
        return None
    return json.loads(out.stdout) if out.stdout.strip() else None


def graph(path: str) -> Any:
    return az("rest", "--method", "get", "--url", f"{GRAPH}{path}", check=False)


def fail(message: str) -> None:
    sys.exit(f"preflight FAILED: {message}")


def deployer() -> str:
    """Postgres admin name (UPN) of the `az login` user."""
    if az("account", "show")["user"]["type"] != "user":
        fail(
            "azd provision runs as a person (az login with your account). CI deploys code only "
            "(.github/workflows/azure-dev.yml); infra changes are applied with `azd up`."
        )
    return az("ad", "signed-in-user", "show")["userPrincipalName"]


def check_app_registration_rights() -> str:
    policy = graph("/policies/authorizationPolicy") or {}
    if policy.get("defaultUserRolePermissions", {}).get("allowedToCreateApps"):
        return "users can register apps"
    roles = (graph("/me/memberOf/microsoft.graph.directoryRole") or {}).get("value", [])
    names = [
        APP_ADMIN_ROLE_TEMPLATES[r["roleTemplateId"]]
        for r in roles
        if r.get("roleTemplateId") in APP_ADMIN_ROLE_TEMPLATES
    ]
    if names:
        return names[0]
    if not policy:
        print("preflight: WARN could not read the tenant app-registration policy; continuing")
        return "unknown"
    fail(
        "you can't create app registrations in this tenant. Ask an admin for the Application Developer role."
    )
    return ""


def check_model_quota(env: dict[str, str]) -> str:
    location = env_or_azd("AZURE_AI_LOCATION", env) or env_or_azd("AZURE_LOCATION", env)
    model = env_or_azd("AZURE_AI_MODEL_NAME", env, "gpt-5.6-luna")
    sku = env_or_azd("AZURE_AI_MODEL_SKU", env, "GlobalStandard")
    capacity = int(env_or_azd("AZURE_AI_MODEL_CAPACITY", env, "30") or 30)
    account, group = env.get("AZURE_AI_ACCOUNT_NAME"), env.get("AZURE_RESOURCE_GROUP")
    if account and group:
        existing = az(
            "cognitiveservices", "account", "deployment", "list", "-n", account, "-g", group, check=False
        )
        if existing and any(d["properties"]["model"]["name"] == model for d in existing):
            return f"{model} already deployed"
    if not location:
        return "skipped (no location yet)"
    usages = az("cognitiveservices", "usage", "list", "-l", location, check=False) or []
    name = f"OpenAI.{sku}.{model}"
    usage = next((u for u in usages if u["name"]["value"] == name), None)
    if usage is None:
        fail(
            f"{model} ({sku}) is not available in {location}. Set AZURE_AI_LOCATION to a region that has it."
        )
        return ""
    free = int(usage["limit"] - usage["currentValue"])
    if free < capacity:
        fail(
            f"{name} in {location}: {free} free, {capacity} needed. Lower AZURE_AI_MODEL_CAPACITY, pick another "
            "AZURE_AI_LOCATION, or request quota."
        )
    return f"{name} in {location}: {free} free, {capacity} needed"


def public_ip() -> str:
    try:
        return httpx.get("https://api.ipify.org", timeout=10).text.strip()
    except httpx.HTTPError:
        print("preflight: WARN could not detect the public IP; migrate/seed may not reach Postgres")
        return ""


def main() -> None:
    env = azd_env()
    name = deployer()
    print(f"preflight: deployer {name}")
    print(f"preflight: app registrations ok ({check_app_registration_rights()})")
    print(f"preflight: model quota ok ({check_model_quota(env)})")
    values = {"AZURE_PRINCIPAL_NAME": name, "AZURE_PRINCIPAL_TYPE": "User"}
    if ip := public_ip():
        values["CLIENT_IP_ADDRESS"] = ip
    for key, value in values.items():
        if env.get(key) != value:
            subprocess.run(["azd", "env", "set", key, value], check=True, cwd=ROOT, capture_output=True)
    print("preflight: azd env updated (" + ", ".join(values) + ")")


if __name__ == "__main__":
    main()
