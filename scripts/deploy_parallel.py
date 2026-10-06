"""Deploy several azd services at the same time (`azd deploy <service>` runs one service per process).

azd deploys services one by one; ACR builds and revision rollouts are independent, so running them side by
side saves ~1–1.5 min per extra service. Concurrent azd processes can overwrite each other's
SERVICE_<NAME>_IMAGE_NAME in the azd env, so afterwards those values are reset from the running apps.
Like a full `azd deploy`, it then runs deploy_agent.py (skipped when the agent definition is unchanged)
and verify_deployment.py.

Usage: uv run python scripts/deploy_parallel.py [web app-api energy-service]
"""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ["web", "app-api", "energy-service"]
ENV = {**os.environ, "AZD_SKIP_UPDATE_CHECK": "true"}


def deploy(service: str) -> tuple[str, int, float, str]:
    start = time.monotonic()
    proc = subprocess.run(
        ["azd", "deploy", service, "--no-prompt"], cwd=ROOT, env=ENV, capture_output=True, text=True
    )
    return service, proc.returncode, time.monotonic() - start, (proc.stdout + proc.stderr).strip()


def sync_image_names(services: list[str]) -> None:
    rg = subprocess.run(
        ["azd", "env", "get-value", "AZURE_RESOURCE_GROUP"], cwd=ROOT, env=ENV, capture_output=True, text=True
    ).stdout.strip()
    apps = json.loads(
        subprocess.run(
            ["az", "containerapp", "list", "-g", rg, "--query",
             "[].{svc: tags.\"azd-service-name\", image: properties.template.containers[0].image}", "-o", "json"],
            capture_output=True, text=True, check=True,
        ).stdout
    )  # fmt: skip
    for app in apps:
        if app["svc"] in services:
            key = f"SERVICE_{app['svc'].upper().replace('-', '_')}_IMAGE_NAME"
            subprocess.run(["azd", "env", "set", key, app["image"]], cwd=ROOT, env=ENV, check=True)


def main() -> int:
    services = sys.argv[1:] or SERVICES
    unknown = set(services) - set(SERVICES)
    if unknown:
        raise SystemExit(f"Unknown service(s): {', '.join(sorted(unknown))}. Choose from {SERVICES}.")
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(services)) as pool:
        results = list(pool.map(deploy, services))
    failed = False
    for service, code, seconds, output in results:
        print(f"{'OK  ' if code == 0 else 'FAIL'} {service:<15} {seconds:6.0f} s")
        if code != 0:
            failed = True
            print(output[-2000:])
    sync_image_names(services)
    for script in ("deploy_agent.py", "verify_deployment.py"):
        if not failed:
            failed = (
                subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT).returncode != 0
            )
    print(f"Total {time.monotonic() - start:.0f} s (sequential would be ~{sum(r[2] for r in results):.0f} s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
