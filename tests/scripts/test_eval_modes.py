import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture
def run_evals(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("run_evals_under_test", SCRIPTS / "run_evals.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "LAST_FULL", tmp_path / "last-full.json")
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "instructions.md").write_text("v1")
    return module


def test_auto_runs_full_first_then_quick_until_the_agent_changes(run_evals, tmp_path) -> None:  # type: ignore[no-untyped-def]
    patterns = ["agent/*.md"]
    first = run_evals.fingerprint(patterns)
    assert run_evals.resolve_mode("auto", first)[0] == "full"

    run_evals.LAST_FULL.write_text(json.dumps({"fingerprint": first}))
    assert run_evals.resolve_mode("auto", run_evals.fingerprint(patterns))[0] == "quick"

    (tmp_path / "agent" / "instructions.md").write_text("v2")
    assert run_evals.resolve_mode("auto", run_evals.fingerprint(patterns))[0] == "full"


def test_explicit_mode_wins(run_evals) -> None:  # type: ignore[no-untyped-def]
    assert run_evals.resolve_mode("quick", "x") == ("quick", "requested")
    assert run_evals.resolve_mode("full", "x") == ("full", "requested")
