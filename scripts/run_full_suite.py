"""Run the required full test suite in two phases.

Phase 1 runs every test except `process_timing` ones across xdist workers; whole
files stay on one worker (`--dist loadfile`) so module fixtures behave as they do
serially. Phase 2 runs the `process_timing` tests serially, because their
sub-second deadlines are only meaningful on an uncontended host. The marker
partitions the suite, so together the phases select exactly what
`pytest tests/` selects.

    python3 scripts/run_full_suite.py            # both phases, stop on first failure
    python3 scripts/run_full_suite.py --workers 6
    python3 scripts/run_full_suite.py -m 'not slow' --cov=kinocut --junitxml=results.xml
    python3 scripts/run_full_suite.py -- -k audio  # extra args go to both phases
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory

DEFAULT_WORKERS = "auto"


def _phases(workers: str, extra: list[str], marker: str = "") -> list[tuple[str, list[str]]]:
    base = [sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--tb=short", *extra]
    prefix = f"({marker}) and " if marker else ""
    return [
        ("parallel", [*base, "-m", prefix + "not process_timing", "-n", workers, "--dist", "loadfile"]),
        ("process-timing (serial)", [*base, "-m", prefix + "process_timing"]),
    ]


def _run(args: argparse.Namespace, directory: Path) -> int:
    total = time.monotonic()
    collected = False
    serial_collected = False
    suites = ET.Element("testsuites")
    for index, (name, cmd) in enumerate(_phases(args.workers, args.extra, args.marker)):
        if args.cov:
            cmd.extend(f"--cov={source}" if source else "--cov" for source in args.cov)
            if index == 0:
                cmd.extend(["--cov-report=", "--cov-fail-under=0"])
            else:
                cmd.extend(["--cov-append", *(f"--cov-report={report}" for report in args.cov_report)])
        report = directory / f"{index}.xml"
        if args.junitxml:
            cmd.append(f"--junitxml={report}")
        started = time.monotonic()
        print(f"== {name}: {' '.join(cmd[1:])}", flush=True)
        rc = subprocess.call(cmd)
        if args.junitxml and report.exists():
            suites.extend(ET.parse(report).getroot())  # noqa: S314 -- pytest wrote this private temp file
            args.junitxml.parent.mkdir(parents=True, exist_ok=True)
            ET.ElementTree(suites).write(args.junitxml, encoding="utf-8", xml_declaration=True)
        print(f"== {name}: exit {rc} in {time.monotonic() - started:.0f}s", flush=True)
        if rc not in (0, 5):  # 5 = nothing collected, e.g. an extra -k filter matched one phase only
            return rc
        collected = collected or rc == 0
        serial_collected = index > 0 and rc == 0
    if not collected:
        print("== no tests collected in any phase", flush=True)
        return 5
    if args.cov and not serial_collected:
        # Only the serial phase carries --cov-report= (and so the config's
        # fail_under). When it collects nothing, the parallel phase's data was
        # never reported or enforced: do both here instead of skipping coverage.
        enforced = _enforce_coverage(args)
        if enforced != 0:
            return enforced
    print(f"== full suite passed in {time.monotonic() - total:.0f}s", flush=True)
    return 0


def _enforce_coverage(args: argparse.Namespace) -> int:
    """Print the combined coverage report and apply ``fail_under`` from the config.

    ``--cov=<source>`` names packages; ``coverage report --include`` matches file
    paths, so each source becomes a ``*/<source>/*`` glob. A bare ``--cov`` leaves
    the selection to the config, exactly as pytest-cov would.
    """
    sources = [source for source in args.cov if source]
    cmd = [sys.executable, "-m", "coverage", "report"]
    if sources:
        cmd.append("--include=" + ",".join(f"*/{source}/*" for source in sources))
    print(f"== coverage (serial phase collected nothing): {' '.join(cmd[1:])}", flush=True)
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", default=os.environ.get("KINOCUT_TEST_WORKERS", DEFAULT_WORKERS))
    parser.add_argument("-m", dest="marker", default="")
    parser.add_argument("--cov", action="append", nargs="?", const="")
    parser.add_argument("--cov-report", action="append", default=[])
    parser.add_argument("--junitxml", type=Path)
    parser.add_argument("extra", nargs="*", help="additional pytest arguments (after --)")
    args = parser.parse_args(argv)
    if any(arg.startswith(("-m", "--cov", "--junitxml", "-n")) for arg in args.extra):
        parser.error("use the runner's marker, worker, coverage and JUnit options before --")
    with TemporaryDirectory() as directory:
        return _run(args, Path(directory))


if __name__ == "__main__":
    raise SystemExit(main())
