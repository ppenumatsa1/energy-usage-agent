"""LOCAL ONLY: mint a dev token for a synthetic user. Usage: uv run python scripts/dev_token.py a1 [--audience energy-service --scope Energy.Read]"""

import argparse
import os
import sys

from energy_usage_shared.auth import DEV_USERS, mint_dev_token


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("user", choices=sorted(DEV_USERS))
    p.add_argument("--audience", default="app-api")
    p.add_argument("--scope", default="Chat.Ask")
    a = p.parse_args()
    secret = os.environ.get("DEV_JWT_SECRET")
    if not secret:
        sys.exit("DEV_JWT_SECRET is not set")
    u = DEV_USERS[a.user]
    print(mint_dev_token(secret, a.audience, a.scope, u.tid, u.oid, u.name))


if __name__ == "__main__":
    main()
