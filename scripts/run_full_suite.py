"""Run the required full test suite in two phases.

Phase 1 runs every test except `process_timing` ones across xdist workers; whole
files stay on one worker (`--dist loadfile`) so module fixtures behave as they do
serially. Phase 2 runs the `process_timing` tests serially, because their
sub-second deadlines are only meaningful on an uncontended host. The marker
partitions the suite, so together the phases select exactly what
`pytest tests/` selects.

    python3 scripts/run_full_suite.py            # both phases, stop on first failure
    python3 scripts/run_full_suite.py --workers 6
    python3 scripts/run_full_suite.py -- -k audio  # extra args go to both phases
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

DEFAULT_WORKERS = "auto"


def _phases(workers: str, extra: list[str]) -> list[tuple[str, list[str]]]:
    base = [sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--tb=short", *extra]
    return [
        ("parallel", [*base, "-m", "not process_timing", "-n", workers, "--dist", "loadfile"]),
        ("process-timing (serial)", [*base, "-m", "process_timing"]),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", default=os.environ.get("KINOCUT_TEST_WORKERS", DEFAULT_WORKERS))
    parser.add_argument("extra", nargs="*", help="arguments passed to both pytest phases (after --)")
    args = parser.parse_args(argv)
    if any(arg == "-m" or (arg.startswith("-m") and not arg.startswith("--")) for arg in args.extra):
        parser.error("-m is owned by the phase split; filter with -k or paths instead")
    total = time.monotonic()
    collected = False
    for name, cmd in _phases(args.workers, args.extra):
        started = time.monotonic()
        print(f"== {name}: {' '.join(cmd[1:])}", flush=True)
        rc = subprocess.call(cmd)
        print(f"== {name}: exit {rc} in {time.monotonic() - started:.0f}s", flush=True)
        if rc not in (0, 5):  # 5 = nothing collected, e.g. an extra -k filter matched one phase only
            return rc
        collected = collected or rc == 0
    if not collected:
        print("== no tests collected in any phase", flush=True)
        return 5
    print(f"== full suite passed in {time.monotonic() - total:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
