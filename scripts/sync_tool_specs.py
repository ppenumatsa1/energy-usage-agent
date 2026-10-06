"""Write agent/tools/*.json from the energy-service MCP tools/list. `--check` fails if they differ."""

import argparse
import json
import sys
from pathlib import Path

from energy_usage_energy.mcp.specs import tool_specs

TOOLS_DIR = Path(__file__).resolve().parents[1] / "agent" / "tools"


def render(spec: dict) -> str:  # type: ignore[type-arg]
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Exit 1 if agent/tools is out of date.")
    args = parser.parse_args()

    wanted = {f"{s['name']}.json": render(s) for s in tool_specs()}
    existing = {p.name: p.read_text() for p in TOOLS_DIR.glob("*.json")} if TOOLS_DIR.exists() else {}
    if args.check:
        if wanted != existing:
            print(
                "agent/tools is out of date. Run: uv run python scripts/sync_tool_specs.py", file=sys.stderr
            )
            return 1
        print(f"agent/tools is up to date ({len(wanted)} tools).")
        return 0
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in set(existing) - set(wanted):
        (TOOLS_DIR / stale).unlink()
    for name, text in wanted.items():
        (TOOLS_DIR / name).write_text(text)
    print(f"Wrote {len(wanted)} tool specs to {TOOLS_DIR}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
