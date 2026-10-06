"""Run the whole app locally with no Azure: Postgres (pgserver), energy-service, app-api (fake agent) and web.

Usage: uv run python scripts/dev.py [--memory] [--no-web]
  --memory   in-memory synthetic data instead of Postgres (no database needed)
  --no-web   do not start the Vite dev server
Then open http://localhost:5173 and pick a demo user (a1, a2, b1, x1).
"""

import argparse
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time

import httpx
import psycopg
from _common import LOCAL_STATE, ROOT
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ENERGY_PORT, API_PORT = 8001, 8000


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def prepare_database() -> str:
    run("scripts/local_db.py")
    owner = (LOCAL_STATE / "database_url").read_text().strip()
    run("scripts/migrate.py", "--database-url", owner)
    with psycopg.connect(owner) as conn:
        seeded = conn.execute("select exists(select 1 from energy.usage_daily limit 1)").fetchone()
    if not (seeded and seeded[0]):
        run("scripts/seed.py", "--database-url", owner)
    return owner


def as_login(owner: str, user: str) -> str:
    params = conninfo_to_dict(owner)
    params.update(user=user, password=os.environ.get("LOCAL_DB_APP_PASSWORD", "local-dev-only"))
    return make_conninfo(**params)


def wait_healthy(url: str, proc: subprocess.Popen[bytes]) -> None:
    for _ in range(100):
        if proc.poll() is not None:
            raise SystemExit(f"process for {url} exited with {proc.returncode}")
        try:
            if httpx.get(f"{url}/healthz", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise SystemExit(f"{url} did not become healthy")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--no-web", action="store_true")
    args = parser.parse_args()

    secret = os.environ.get("DEV_JWT_SECRET") or secrets.token_urlsafe(32)
    common = {**os.environ, "ENVIRONMENT": "local", "AUTH_MODE": "dev", "DEV_JWT_SECRET": secret}
    energy_env = {**common, "AUTH_AUDIENCE": "energy-service"}
    api_env = {
        **common,
        "AUTH_AUDIENCE": "app-api",
        "AGENT_MODE": os.environ.get("AGENT_MODE", "fake"),
        "OBO_CREDENTIAL": "dev",
        "ENERGY_SERVICE_URL": f"http://localhost:{ENERGY_PORT}",
    }
    if args.memory:
        energy_env["REPOSITORY"] = "memory"
    else:
        owner = prepare_database()
        energy_env["DATABASE_URL"] = as_login(owner, "energy_app")
        api_env["APP_DATABASE_URL"] = as_login(owner, "app_api_app")

    uvicorn = [sys.executable, "-m", "uvicorn", "--factory", "--host", "127.0.0.1"]
    procs: list[subprocess.Popen[bytes]] = []
    try:
        energy = subprocess.Popen(
            [*uvicorn, "--port", str(ENERGY_PORT), "energy_usage_energy.main:create_app"],
            cwd=ROOT,
            env=energy_env,
        )
        procs.append(energy)
        wait_healthy(f"http://localhost:{ENERGY_PORT}", energy)
        api = subprocess.Popen(
            [*uvicorn, "--port", str(API_PORT), "energy_usage_app_api.main:create_app"], cwd=ROOT, env=api_env
        )
        procs.append(api)
        wait_healthy(f"http://localhost:{API_PORT}", api)
        if not args.no_web:
            npm = shutil.which("npm")
            if not npm:
                raise SystemExit("npm not found; use --no-web")
            procs.append(subprocess.Popen([npm, "run", "dev"], cwd=ROOT / "frontend"))
        print(f"\napp-api http://localhost:{API_PORT}  energy-service http://localhost:{ENERGY_PORT}", end="")
        print("" if args.no_web else "  web http://localhost:5173", "\nCtrl+C to stop.", flush=True)
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
