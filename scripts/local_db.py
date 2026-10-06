"""Start a local Postgres 16 without Docker (pgserver) and write its URL to .local/database_url.

Usage: uv run python scripts/local_db.py [--stop]
If Docker is available you can use `docker compose up -d postgres` instead.
"""

import argparse

import pgserver
from _common import LOCAL_STATE


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    data_dir = LOCAL_STATE / "pgdata"
    data_dir.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(str(data_dir), cleanup_mode=None)
    if args.stop:
        server.cleanup()
        server._instance_cleanup()  # type: ignore[attr-defined]
        print("stopped")
        return
    url = server.get_uri()
    (LOCAL_STATE / "database_url").write_text(url)
    print(url)


if __name__ == "__main__":
    main()
