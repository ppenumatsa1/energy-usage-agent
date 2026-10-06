"""Admin onboarding (BR-2): map a signed-in user (tid, oid) to a customer. Values are passed at runtime
and must never be committed.

Usage:
  uv run python scripts/map_user.py --tid <guid> --oid <guid> --customer-id <uuid> [--azure] [--remove]
  uv run python scripts/map_user.py --me --azure    # the `az login` user -> first demo customer, if unmapped

`--me` runs in the postprovision hook so the deployer can chat right after `azd up`. It skips service
principals (CI) and never changes an existing mapping.
"""

import argparse
import json
import subprocess
import sys

import psycopg
from _common import ROOT, owner_conninfo

sys.path.insert(0, str(ROOT / "services" / "energy-service" / "src"))
from energy_usage_energy.testing.synthetic import CUSTOMERS  # noqa: E402

INSERT = (
    "INSERT INTO energy.user_customer (tid, oid, customer_id) VALUES (%s, %s, %s) ON CONFLICT (tid, oid) DO "
)
INSERT_KEEP = INSERT + "NOTHING"
INSERT_OR_UPDATE = INSERT + "UPDATE SET customer_id = EXCLUDED.customer_id"


def signed_in_user() -> tuple[str, str] | None:
    """(tid, oid) of the `az login` user, or None for a service principal."""

    def az(*args: str) -> dict[str, str]:
        return json.loads(
            subprocess.run(["az", *args, "-o", "json"], capture_output=True, text=True, check=True).stdout
        )

    account = az("account", "show")
    if account["user"]["type"] != "user":
        return None
    return account["tenantId"], az("ad", "signed-in-user", "show")["id"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tid")
    p.add_argument("--oid")
    p.add_argument("--customer-id")
    p.add_argument(
        "--me", action="store_true", help="Map the az login user to the first demo customer if unmapped."
    )
    p.add_argument("--remove", action="store_true")
    p.add_argument("--azure", action="store_true")
    p.add_argument("--database-url")
    a = p.parse_args()

    if a.me:
        who = signed_in_user()
        if who is None:
            print("map_user: deployer is a service principal; skipped")
            return
        a.tid, a.oid = who
        a.customer_id = a.customer_id or CUSTOMERS[0].customer_id
    if not a.tid or not a.oid:
        p.error("--tid and --oid are required (or --me)")

    with psycopg.connect(owner_conninfo(a.azure, a.database_url), autocommit=True) as conn:
        if a.remove:
            conn.execute("DELETE FROM energy.user_customer WHERE tid=%s AND oid=%s", (a.tid, a.oid))
            print("removed")
            return
        if not a.customer_id:
            p.error("--customer-id is required unless --remove")
        cur = conn.execute(INSERT_KEEP if a.me else INSERT_OR_UPDATE, (a.tid, a.oid, a.customer_id))
        print("mapped" if cur.rowcount else "already mapped; unchanged")


if __name__ == "__main__":
    main()
