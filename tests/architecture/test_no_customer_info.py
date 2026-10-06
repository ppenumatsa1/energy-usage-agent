"""No customer information in the repo. Terms come from the CUSTOMER_DENYLIST env var (newline separated),
never from a file, so the list itself is never committed. CI sets it from a secret."""

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "node_modules", "dist", ".local", ".azure", ".pytest_cache", ".ruff_cache",
             "__pycache__", ".mypy_cache"}  # fmt: skip


def _terms() -> list[str]:
    return [t.strip().lower() for t in os.environ.get("CUSTOMER_DENYLIST", "").splitlines() if t.strip()]


def _files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if path.is_file() and not (set(rel.parts) & SKIP_DIRS) and path.stat().st_size < 2_000_000:
            out.append(path)
    return out


@pytest.mark.skipif(not _terms(), reason="CUSTOMER_DENYLIST not set")
def test_no_denylisted_terms() -> None:
    terms = _terms()
    hits = []
    for path in _files():
        rel = str(path.relative_to(ROOT)).lower()
        try:
            text = path.read_text(errors="ignore").lower()
        except OSError:
            continue
        if any(t in text or t in rel for t in terms):
            hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"denylisted terms found in: {hits}"  # terms themselves are never printed
