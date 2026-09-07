#!/usr/bin/env python3
"""Instrument a bounded pytest collection run on Windows CI."""

from __future__ import annotations

import argparse
import faulthandler
import os
import platform
import sys
import threading
import time


DEFAULT_WATCHDOG_SECONDS = 120
MIN_WATCHDOG_SECONDS = 1
MAX_WATCHDOG_SECONDS = 600
HEARTBEAT_SECONDS = 15
HEARTBEAT_JOIN_SECONDS = 2
MAX_FIELD_CHARS = 512


def _watchdog_seconds(value: str) -> int:
    parsed = int(value)
    if not MIN_WATCHDOG_SECONDS <= parsed <= MAX_WATCHDOG_SECONDS:
        raise argparse.ArgumentTypeError(
            f"watchdog seconds must be between {MIN_WATCHDOG_SECONDS} and {MAX_WATCHDOG_SECONDS}"
        )
    return parsed


def _safe(value: object) -> str:
    escaped = str(value).encode("unicode_escape", errors="backslashreplace").decode("ascii")
    if len(escaped) > MAX_FIELD_CHARS:
        return escaped[:MAX_FIELD_CHARS] + "...[truncated]"
    return escaped


def _write(event: str, **fields: object) -> None:
    rendered = " ".join(f"{key}={_safe(value)}" for key, value in fields.items())
    sys.stderr.write(f"{event}{' ' if rendered else ''}{rendered}\n")
    sys.stderr.flush()


def _elapsed(started: float) -> str:
    return f"{time.monotonic() - started:.3f}"


def _heartbeat(stop: threading.Event, started: float) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        _write("DIAG_HEARTBEAT", elapsed=_elapsed(started))


class CollectionPlugin:
    def __init__(self, started: float) -> None:
        self.started = started
        self.collected = 0
        self.active_collectors: set[int] = set()

    def pytest_make_collect_report(self, collector: object):
        nodeid = str(getattr(collector, "nodeid", ""))
        collector_name = type(collector).__name__
        identity = id(collector)
        if identity in self.active_collectors:
            raise RuntimeError("collector report hook re-entered for the same object")
        self.active_collectors.add(identity)
        _write("COLLECT_START", elapsed=_elapsed(self.started), collector=collector_name, nodeid=nodeid)
        try:
            report = yield
        except Exception:
            _write(
                "COLLECT_DONE", elapsed=_elapsed(self.started), collector=collector_name, nodeid=nodeid, outcome="error"
            )
            raise
        finally:
            self.active_collectors.discard(identity)
        outcome = str(getattr(report, "outcome", "unknown"))
        _write("COLLECT_DONE", elapsed=_elapsed(self.started), collector=collector_name, nodeid=nodeid, outcome=outcome)
        return report

    def pytest_collection_finish(self, session: object) -> None:
        if self.active_collectors:
            raise RuntimeError("collector report pairing incomplete")
        self.collected = len(getattr(session, "items", ()))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--watchdog-seconds",
        type=_watchdog_seconds,
        default=DEFAULT_WATCHDOG_SECONDS,
    )
    parser.add_argument("--path", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="backslashreplace", write_through=True)
    started = time.monotonic()
    stop = threading.Event()
    faulthandler.enable(file=sys.stderr, all_threads=True)
    faulthandler.dump_traceback_later(
        args.watchdog_seconds,
        repeat=False,
        file=sys.stderr,
        exit=True,
    )
    _write(
        "DIAG_START",
        utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        elapsed=_elapsed(started),
        pid=os.getpid(),
        python=platform.python_version(),
        platform=platform.platform(),
        runner_os=os.environ.get("RUNNER_OS", ""),
        image_os=os.environ.get("ImageOS", ""),  # noqa: SIM112 - GitHub's documented variable uses this case.
        github_sha=os.environ.get("GITHUB_SHA", ""),
    )
    heartbeat = threading.Thread(target=_heartbeat, args=(stop, started), daemon=True)
    heartbeat.start()
    plugin = CollectionPlugin(started)
    try:
        import pytest

        pytest.hookimpl(wrapper=True)(CollectionPlugin.pytest_make_collect_report)
        return_code = pytest.main(
            [
                "--collect-only",
                "-vv",
                "-s",
                "--tb=short",
                "--color=no",
                "-o",
                "console_output_style=classic",
                *args.path,
            ],
            plugins=[plugin],
        )
    finally:
        faulthandler.cancel_dump_traceback_later()
        stop.set()
        heartbeat.join(timeout=HEARTBEAT_JOIN_SECONDS)
    _write("DIAG_RESULT", elapsed=_elapsed(started), rc=int(return_code), collected=plugin.collected)
    return int(return_code)


if __name__ == "__main__":
    raise SystemExit(main())
