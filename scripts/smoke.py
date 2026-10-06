"""Smoke-test a running stack: /api/me, /api/status, chat (JSON and SSE), stored history.

Usage:
  uv run python scripts/smoke.py                                   # local dev stack, demo user a1
  uv run python scripts/smoke.py --base-url https://<web> --token "$TOKEN"   # Entra: a user token for app-api
"""

import argparse
import json
import sys

import httpx


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", help="Bearer token for app-api (Entra mode). Omit to use dev sign-in.")
    parser.add_argument("--user", default="a1", help="Dev user when --token is not given.")
    parser.add_argument("--question", default="How much energy did I use last month?")
    args = parser.parse_args()

    results: list[bool] = []
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=90) as http:
        token = args.token
        if not token:
            r = http.post("/api/dev/token", json={"user": args.user})
            if not check("dev sign-in", r.status_code == 200, str(r.status_code)):
                return 1
            token = r.json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}

        r = http.get("/api/me", headers=headers)
        results.append(
            check("GET /api/me", r.status_code == 200 and r.json().get("onboarded") is True, r.text[:120])
        )

        r = http.get("/api/status", headers=headers)
        down = (
            [c["id"] for c in r.json().get("components", []) if c["status"] != "ok"]
            if r.status_code == 200
            else []
        )
        results.append(check("GET /api/status", r.status_code == 200 and not down, f"down={down}"))

        r = http.post("/api/chat", json={"message": args.question}, headers=headers)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        rows = len((body.get("table") or {}).get("rows", []))
        steps = len((body.get("trace") or {}).get("steps", []))
        results.append(check("POST /api/chat (json)", r.status_code == 200 and body.get("status") == "ok" and rows > 0 and steps > 0,
                             f"status={body.get('status')} rows={rows} steps={steps} answer={body.get('answer', '')[:80]!r}"))  # fmt: skip

        events: list[str] = []
        last: dict = {}  # type: ignore[type-arg]
        with http.stream("POST", "/api/chat", json={"message": args.question},
                         headers={**headers, "Accept": "text/event-stream"}) as s:  # fmt: skip
            event = ""
            for line in s.iter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                    events.append(event)
                elif line.startswith("data:") and event == "result":
                    last = json.loads(line.split(":", 1)[1])
        results.append(check("POST /api/chat (sse)", bool(events) and events[-1] == "result" and last.get("status") == "ok",
                             f"events={events}"))  # fmt: skip

        r = http.get("/api/conversations", headers=headers)
        results.append(check("GET /api/conversations", r.status_code == 200 and len(r.json()) >= 1))

        cid = body.get("conversationId")
        r = http.get(f"/api/conversations/{cid}", headers=headers)
        turns = r.json().get("turns", []) if r.status_code == 200 else []
        results.append(check("GET /api/conversations/{id} (history)",
                             len(turns) == 1 and turns[0]["response"]["answer"] == body.get("answer"), f"turns={len(turns)}"))  # fmt: skip
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
