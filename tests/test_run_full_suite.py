"""Keep the two-phase full-suite runner exhaustive and its serial list honest."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.conftest import PROCESS_TIMING_FILES

ROOT = Path(__file__).resolve().parents[1]


def _runner():
    spec = importlib.util.spec_from_file_location("run_full_suite", ROOT / "scripts" / "run_full_suite.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_process_timing_file_exists():
    missing = sorted(name for name in PROCESS_TIMING_FILES if not (ROOT / "tests" / name).is_file())
    assert not missing, f"stale PROCESS_TIMING_FILES entries: {missing}"


def _marker_expr(cmd: list[str]) -> str:
    return cmd[len(cmd) - 1 - cmd[::-1].index("-m") + 1]


def test_phases_partition_the_suite_on_the_marker():
    phases = dict(_runner()._phases("4", ["-k", "x"]))
    parallel, serial = phases["parallel"], phases["process-timing (serial)"]
    assert _marker_expr(parallel) == "not process_timing"
    assert _marker_expr(serial) == "process_timing"
    assert "-n" in parallel and "-n" not in serial
    for cmd in (parallel, serial):
        assert cmd[cmd.index("pytest") + 1] == "tests/"
        assert {"-x", "-k"} <= set(cmd)
