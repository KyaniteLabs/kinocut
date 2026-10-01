"""Reject a green Hyperframes integration job that did not execute its tests."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import NoReturn
from xml.etree import ElementTree

MAX_REPORT_BYTES = 64 * 1024
MIN_EXECUTED_CASES = 2
COUNTERS = ("tests", "skipped", "failures", "errors")


def _reject(reason: str) -> NoReturn:
    raise SystemExit(f"Hyperframes integration report rejected: {reason}")


def _totals(element, expected: tuple[int, int, int, int]) -> None:
    values = []
    for name in COUNTERS:
        raw = element.get(name, "")
        if not raw.isascii() or not raw.isdecimal() or len(raw) > 6:
            _reject("invalid suite counters")
        values.append(int(raw))
    if tuple(values) != expected:
        _reject("suite counters disagree with executed cases")


def check_results(path: Path) -> int:
    """Accept only bounded pytest JUnit with at least two successful cases."""
    try:
        with path.open("rb") as report:
            payload = report.read(MAX_REPORT_BYTES + 1)
    except OSError:
        _reject("report is unavailable")
    if len(payload) > MAX_REPORT_BYTES:
        _reject("report exceeds its byte limit")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        _reject("report is not UTF-8")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        _reject("unsupported XML declarations")
    try:
        root = ElementTree.fromstring(text)  # noqa: S314 - bounded XML; DTD/entities rejected.
    except ElementTree.ParseError:
        _reject("malformed XML")
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites" and all(child.tag == "testsuite" for child in root):
        suites = list(root)
    else:
        _reject("unsupported report structure")
    if any(element.tag in {"skipped", "failure", "error"} for element in root.iter()):
        _reject("skipped or unsuccessful tests")
    executed = 0
    for suite in suites:
        if suite.find("testsuite") is not None:
            _reject("nested suites are unsupported")
        cases = suite.findall("testcase")
        _totals(suite, (len(cases), 0, 0, 0))
        executed += len(cases)
    if len(list(root.iter("testcase"))) != executed:
        _reject("unsupported case placement")
    if root.tag == "testsuites" and any(name in root.attrib for name in COUNTERS):
        _totals(root, (executed, 0, 0, 0))
    if executed < MIN_EXECUTED_CASES:
        _reject("fewer than two tests executed")
    return executed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        _reject("expected one JUnit report")
    print(f"Hyperframes integration: {check_results(Path(sys.argv[1]))} executed, zero skipped or unsuccessful")
