"""Run the golden set through the deployed app, check it, and score it with a Foundry evaluation.

Tools run inside app-api (user OBO token), so Foundry cannot replay them. Instead:
  1. Each golden query goes through `POST /api/chat` as a real signed-in user.
  2. Deterministic checks: expected status, expected tools called, rows returned for `ok`.
  3. The captured query, answer, tool calls and tool definitions are submitted to a Foundry
     evaluation with built-in judges (intent resolution, task adherence, tool call accuracy, relevance).
Results are saved under agent/.foundry/results/.

Modes (full is ~5.5 min, quick ~20 s; see agent/eval.yaml `policy`):
  quick  rows tagged `smoke`, deterministic checks only
  local  all rows, deterministic checks only
  full   all rows + Foundry judges
  auto   (default) full when agent-shaping files changed since the last full run, otherwise quick

Usage:
  uv run python scripts/run_evals.py --base-url https://<web> --token "$TOKEN"            # auto
  uv run python scripts/run_evals.py --base-url https://<web> --token "$TOKEN" --mode full
  uv run python scripts/run_evals.py --mode local            # local dev stack
Values from the environment or `azd env get-values`:
  AZURE_AI_PROJECT_ENDPOINT, AZURE_AI_MODEL_DEPLOYMENT_NAME (judge model).
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import azd_env, env_or_azd  # noqa: E402

AGENT_DIR = Path(__file__).resolve().parents[1] / "agent"
ROOT = AGENT_DIR.parent
RESULTS_DIR = AGENT_DIR / ".foundry" / "results"
LAST_FULL = RESULTS_DIR / "last-full.json"
# Agent judges get the conversation as messages (system prompt + tool calls + tool results) so they can
# check scope and evidence; relevance only needs the question and the final answer text.
JUDGES = {
    "intent_resolution": {
        "query": "query_messages",
        "response": "response_messages",
        "tool_definitions": "tool_definitions",
    },
    "task_adherence": {
        "query": "query_messages",
        "response": "response_messages",
        "tool_definitions": "tool_definitions",
    },
    "tool_call_accuracy": {
        "query": "query_messages",
        "response": "response_messages",
        "tool_definitions": "tool_definitions",
    },
    "relevance": {"query": "query", "response": "response"},
}
MAX_RESULT_ROWS = 50


def load_golden(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def fingerprint(patterns: list[str]) -> str:
    """Hash of the files that shape agent behavior (paths relative to the repo root)."""
    digest = hashlib.sha256()
    files = sorted(
        {f for pat in patterns for f in ROOT.glob(pat) if f.is_file() and "__pycache__" not in f.parts}
    )
    for f in files:
        digest.update(str(f.relative_to(ROOT)).encode())
        digest.update(f.read_bytes())
    return digest.hexdigest()


def resolve_mode(mode: str, current: str) -> tuple[str, str]:
    if mode != "auto":
        return mode, "requested"
    last = json.loads(LAST_FULL.read_text()).get("fingerprint") if LAST_FULL.is_file() else None
    if last == current:
        return "quick", "agent unchanged since the last full run"
    return "full", "no previous full run" if last is None else "agent changed since the last full run"


def run_queries(base_url: str, token: str | None, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=180) as http:
        if not token:
            r = http.post("/api/dev/token", json={"user": "a1"})
            r.raise_for_status()
            token = r.json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        for i, row in enumerate(rows, 1):
            start = time.perf_counter()
            r = http.post("/api/chat", json={"message": row["query"]}, headers=headers)
            ms = round((time.perf_counter() - start) * 1000)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            steps = (body.get("trace") or {}).get("steps", [])
            item = {
                **row,
                "http_status": r.status_code,
                "status": body.get("status"),
                "answer": body.get("answer", r.text[:300]),
                "tools": [s["tool"] for s in steps],
                "tool_calls": [
                    {
                        "type": "tool_call",
                        "tool_call_id": f"call_{i}_{n}",
                        "name": s["tool"],
                        "arguments": s["arguments"],
                    }
                    for n, s in enumerate(steps)
                ],
                "steps": steps,
                "table": body.get("table"),
                "chart": body.get("chart"),
                "result_ids": (body.get("trace") or {}).get("resultIds", []),
                "rows": len((body.get("table") or {}).get("rows", [])),
                "correlation_id": body.get("correlationId"),
                "latency_ms": ms,
            }
            item["checks"] = deterministic_checks(item)
            item["passed"] = all(item["checks"].values())
            print(f"{'PASS' if item['passed'] else 'FAIL'}  [{ms:>6} ms] {row['query'][:60]:<60} "
                  f"status={item['status']} tools={item['tools']}")  # fmt: skip
            out.append(item)
    return out


def deterministic_checks(item: dict[str, Any]) -> dict[str, bool]:
    checks = {
        "http_200": item["http_status"] == 200,
        "status": item["status"] == item["expected_status"],
        "expected_tools_called": set(item["expected_tools"]) <= set(item["tools"]),
    }
    if item["expected_status"] == "refused":
        checks["no_tools_when_refused"] = not item["tools"]
    if item["expected_status"] == "ok":
        checks["rows_returned"] = item["rows"] > 0
    return checks


def tool_definitions() -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted((AGENT_DIR / "tools").glob("*.json"))]


def response_messages(r: dict[str, Any]) -> list[dict[str, Any]]:
    """The agent's side of the turn in the agent-evaluator message format: tool calls, tool results and
    the final structured output (the JSON object the instructions require). Rows come from the app's
    table, which is built only from the primary tool result the agent cited."""
    messages: list[dict[str, Any]] = []
    table = r.get("table") or {}
    result_ids = r.get("result_ids") or []
    ok_ids = [s.get("resultId") for s in r["steps"] if s.get("resultId")]
    primary = next((rid for rid in result_ids if rid in ok_ids), ok_ids[-1] if ok_ids else None)
    for call, step in zip(r["tool_calls"], r["steps"], strict=True):
        messages.append({"role": "assistant", "content": [call]})
        result: dict[str, Any] = {"status": step["status"]}
        if step["status"] == "ok":
            result |= {
                "result_id": step.get("resultId"),
                "row_count": step.get("rows"),
                "assumptions": step.get("assumptions", []),
                "summary": step.get("summary", {}),
            }
            if step.get("resultId") == primary and table.get("rows"):
                result["columns"] = [c.get("key") for c in table.get("columns", [])]
                result["rows"] = table["rows"][:MAX_RESULT_ROWS]
        else:
            result |= {"code": step.get("errorCode"), "message": step.get("errorMessage")}
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["tool_call_id"],
                "content": [{"type": "tool_result", "tool_result": result}],
            }
        )
    output = {"answer": r["answer"], "status": r["status"], "result_ids": result_ids, "chart": r.get("chart")}
    messages.append({"role": "assistant", "content": [{"type": "text", "text": json.dumps(output)}]})
    return messages


def foundry_eval(results: list[dict[str, Any]], endpoint: str, model: str, name: str) -> dict[str, Any]:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import TestingCriterionAzureAIEvaluator
    from azure.identity import DefaultAzureCredential
    from openai.types.eval_create_params import DataSourceConfigCustom

    defs = tool_definitions()
    system = (AGENT_DIR / "instructions.md").read_text()
    items = [
        {
            "item": {
                "query": r["query"],
                "response": r["answer"],
                "query_messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": [{"type": "text", "text": r["query"]}]},
                ],
                "response_messages": response_messages(r),
                "tool_definitions": defs,
            }
        }
        for r in results
    ]
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "response": {"type": "string"},
            "query_messages": {"type": "array"},
            "response_messages": {"type": "array"},
            "tool_definitions": {"type": "array"},
        },
        "required": ["query", "response"],
    }
    criteria = [
        TestingCriterionAzureAIEvaluator(
            type="azure_ai_evaluator",
            name=judge,
            evaluator_name=f"builtin.{judge}",
            initialization_parameters={"deployment_name": model},
            data_mapping={param: f"{{{{item.{field}}}}}" for param, field in fields.items()},
        )
        for judge, fields in JUDGES.items()
    ]
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=endpoint, credential=credential) as project,
        project.get_openai_client() as client,
    ):
        ev = client.evals.create(
            name=name,
            data_source_config=DataSourceConfigCustom(
                type="custom", item_schema=schema, include_sample_schema=False
            ),
            testing_criteria=criteria,  # type: ignore[arg-type]
        )
        run = client.evals.runs.create(
            eval_id=ev.id,
            name=f"{name}-{datetime.now(UTC):%Y%m%d-%H%M%S}",
            data_source={"type": "jsonl", "source": {"type": "file_content", "content": items}},  # type: ignore[arg-type]
        )
        print(f"Foundry eval {ev.id} run {run.id} started; polling…")
        while run.status not in ("completed", "failed", "canceled"):
            time.sleep(10)
            run = client.evals.runs.retrieve(run_id=run.id, eval_id=ev.id)
        per_item = [o.model_dump() for o in client.evals.runs.output_items.list(run_id=run.id, eval_id=ev.id)]
        return {
            "eval_id": ev.id,
            "run_id": run.id,
            "status": run.status,
            "report_url": getattr(run, "report_url", None),
            "result_counts": run.result_counts.model_dump() if run.result_counts else None,
            "per_testing_criteria_results": [
                c.model_dump() for c in (run.per_testing_criteria_results or [])
            ],
            "error": run.error.model_dump() if getattr(run, "error", None) else None,
            "output_items": per_item,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", help="Entra user token for app-api. Omit to use dev sign-in (local).")
    parser.add_argument("--mode", choices=["auto", "quick", "local", "full"], default="auto")
    parser.add_argument("--local-only", action="store_true", help="Same as --mode local.")
    args = parser.parse_args()

    spec = yaml.safe_load((AGENT_DIR / "eval.yaml").read_text())
    threshold = float(spec.get("options", {}).get("pass_threshold", 0.8))
    current = fingerprint(spec["policy"]["full_when_changed"])
    mode, why = resolve_mode("local" if args.local_only else args.mode, current)
    golden = load_golden(AGENT_DIR / spec["dataset"]["local_uri"])
    if mode == "quick":
        golden = [row for row in golden if "smoke" in row.get("tags", [])]
    print(f"Mode: {mode} ({why}); {len(golden)} rows")
    results = run_queries(args.base_url, args.token, golden)
    pass_rate = sum(r["passed"] for r in results) / len(results)
    print(f"\nDeterministic: {sum(r['passed'] for r in results)}/{len(results)} passed ({pass_rate:.0%}); "
          f"threshold {threshold:.0%}")  # fmt: skip

    report: dict[str, Any] = {"timestamp": datetime.now(UTC).isoformat(), "base_url": args.base_url,
                              "mode": mode, "deterministic_pass_rate": pass_rate, "items": results}  # fmt: skip
    if mode == "full":
        env = azd_env()
        endpoint = env_or_azd("AZURE_AI_PROJECT_ENDPOINT", env)
        model = env_or_azd("AZURE_AI_MODEL_DEPLOYMENT_NAME", env)
        if not endpoint or not model:
            raise SystemExit("AZURE_AI_PROJECT_ENDPOINT / AZURE_AI_MODEL_DEPLOYMENT_NAME not set.")
        report["foundry"] = foundry_eval(results, endpoint, model, spec["name"])
        for c in report["foundry"]["per_testing_criteria_results"]:
            total = c.get("passed", 0) + c.get("failed", 0)
            print(f"  {c.get('testing_criteria')}: {c.get('passed')}/{total} passed")
        print(f"Foundry run: {report['foundry']['status']}  report: {report['foundry']['report_url']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"golden-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"Saved {out.relative_to(AGENT_DIR.parent)}")
    passed = pass_rate >= threshold
    if mode == "full" and passed:
        LAST_FULL.write_text(json.dumps({"fingerprint": current, "results": out.name}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
