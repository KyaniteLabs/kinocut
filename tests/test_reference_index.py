"""The generated indexes in the reference docs must match the code."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reference_doc_indexes_are_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_reference_index.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
