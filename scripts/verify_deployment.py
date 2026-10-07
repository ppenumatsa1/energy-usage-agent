"""Post-deploy verification: the same checks for a person, an agent or CI.

  1. No sign-in needed: web is up, /config.json matches the app registrations, /api/chat rejects a missing token.
  2. With a user token: smoke (scripts/smoke.py) and evals (scripts/run_evals.py --mode auto).
  3. Telemetry: one chat turn shows up in App Insights as one trace with app-api, Foundry and energy-service spans
     (without a token: the rejected request from step 1 arrives).

User token: VERIFY_TOKEN if set; otherwise, for an `az login` user, `az account get-access-token --scope $API_SCOPE`
(needs ENTRA_PREAUTHORIZE_AZURE_CLI=true, the dev default). A service principal (CI) has no user, so steps 2 and
the chat trace are skipped unless VERIFY_TOKEN is provided.

Runs in the postdeploy hook and after scripts/deploy_parallel.py. Manual: uv run python scripts/verify_deployment.py
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from _common import ROOT, azd_env, env_or_azd

TRACE_ROLES = {"app-api", "responsesapi", "energy-service"}


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return ok


def user_token(scope: str) -> str | None:
    if token := os.environ.get("VERIFY_TOKEN"):
        return token
    account = json.loads(subprocess.run(["az", "account", "show", "-o", "json"], capture_output=True, text=True,
                                        check=True).stdout)  # fmt: skip
    if account["user"]["type"] != "user":
        return None
    out = subprocess.run(["az", "account", "get-access-token", "--scope", scope, "--query", "accessToken", "-o", "tsv"],
                         capture_output=True, text=True)  # fmt: skip
    if out.returncode != 0:
        print(f"WARN  no user token from az: {out.stderr.strip()[:200]}")
        return None
    return out.stdout.strip()


def wait_until_up(http: httpx.Client, timeout: int) -> bool:
    """A fresh environment's first revision can take minutes to answer; wait instead of failing on a timeout."""
    deadline, last = time.monotonic() + timeout, ""
    while time.monotonic() < deadline:
        try:
            r = http.get("/", timeout=15)
            if r.status_code == 200:
                return True
            last = str(r.status_code)
        except httpx.HTTPError as e:
            last = type(e).__name__
        print(f"WAIT  web not ready ({last}); retrying", flush=True)
        time.sleep(10)
    return check("GET / (web)", False, f"not ready after {timeout}s: {last}")


def no_user_checks(http: httpx.Client, env: dict[str, str]) -> list[bool]:
    results = [check("GET / (web)", http.get("/").status_code == 200)]
    config = http.get("/config.json").json()
    results.append(check("GET /config.json matches app registrations",
                         config.get("clientId") == env.get("WEB_APP_ID") and config.get("apiScope") == env.get("API_SCOPE"),
                         f"clientId={config.get('clientId')}"))  # fmt: skip
    r = http.post("/api/chat", json={"message": "verify"})
    results.append(check("POST /api/chat without token -> 401", r.status_code == 401, str(r.status_code)))
    return results


def query(env: dict[str, str], kql: str) -> list[list[Any]]:
    out = subprocess.run(
        ["az", "monitor", "app-insights", "query", "--app", env["APPLICATIONINSIGHTS_NAME"],
         "-g", env["AZURE_RESOURCE_GROUP"], "--analytics-query", kql, "--query", "tables[0].rows", "-o", "json"],
        capture_output=True, text=True,
    )  # fmt: skip
    rows = json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else []
    # Dynamic columns (make_set) come back as JSON strings.
    return [[json.loads(v) if isinstance(v, str) and v.startswith("[") else v for v in row] for row in rows]


def telemetry_check(env: dict[str, str], since: str, chat: bool, timeout: int) -> bool:
    if chat:
        label = "App Insights: chat trace spans " + ", ".join(sorted(TRACE_ROLES))
        kql = (f"let ops = requests | where timestamp > datetime({since}) and name == 'POST /api/chat' "
               "and resultCode == '200' | project operation_Id; "
               "union requests, dependencies | where operation_Id in (ops) "
               "| summarize roles = make_set(cloud_RoleName) by operation_Id")  # fmt: skip
    else:
        label = "App Insights: rejected chat request recorded"
        kql = (f"requests | where timestamp > datetime({since}) and name == 'POST /api/chat' "
               "and resultCode == '401' | summarize roles = make_set(cloud_RoleName) by operation_Id")  # fmt: skip
    expected = TRACE_ROLES if chat else {"app-api"}
    deadline, seen = time.monotonic() + timeout, set()
    while time.monotonic() < deadline:
        rows = query(env, kql)
        seen = set().union(*(set(roles) for _, roles in rows)) if rows else set()
        if any(expected <= set(roles) for _, roles in rows):
            return check(label, True)
        time.sleep(20)
    return check(label, False, f"seen={sorted(seen)} after {timeout}s")


def run(script: str, *args: str) -> bool:
    print(f"\n--- {script} ---", flush=True)
    return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], cwd=ROOT).returncode == 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--eval-mode", default="auto", choices=["auto", "quick", "full", "skip"])
    p.add_argument(
        "--telemetry-timeout", type=int, default=300, help="Seconds to wait for App Insights ingestion."
    )
    p.add_argument(
        "--ready-timeout", type=int, default=300, help="Seconds to wait for the web app to answer."
    )
    a = p.parse_args()

    env = azd_env()
    base = env_or_azd("FRONTEND_URL", env)
    scope = env_or_azd("API_SCOPE", env)
    if not base or not scope:
        sys.exit("verify: FRONTEND_URL / API_SCOPE missing; provision first")
    since = datetime.now(UTC).isoformat()

    with httpx.Client(base_url=base.rstrip("/"), timeout=60) as http:
        if not wait_until_up(http, a.ready_timeout):
            print("\nverify: web never became ready")
            return 1
        results = no_user_checks(http, env)

    token = user_token(scope)
    if token:
        results.append(run("smoke.py", "--base-url", base, "--token", token))
        if a.eval_mode != "skip":
            results.append(run("run_evals.py", "--base-url", base, "--token", token, "--mode", a.eval_mode))
    else:
        print("SKIP  smoke + evals: no user token (service principal). Set VERIFY_TOKEN to include them.")

    print()
    results.append(telemetry_check(env, since, chat=bool(token), timeout=a.telemetry_timeout))
    print(f"\nverify: {sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
