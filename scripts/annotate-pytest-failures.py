"""Publish bounded JUnit failures through GitHub check annotations.

Diagnostics only: the pytest step retains its exit status. Report contents are
untrusted, so annotations never interpolate file properties or command syntax.
"""

from __future__ import annotations

import os
import stat
import sys
from xml.etree import ElementTree

MAX_REPORT_BYTES = 8_388_608
MAX_FAILURE_ANNOTATIONS = 10
MAX_MESSAGE_CHARACTERS = 4096
MAX_IDENTITY_CHARACTERS = 512


def _annotation(kind: str, message: str) -> None:
    bounded = message[:MAX_MESSAGE_CHARACTERS]
    escaped = bounded.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{kind} title=Pytest diagnostics::{escaped}")


def _read_report(path: str) -> str | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as report:
            if not stat.S_ISREG(os.fstat(report.fileno()).st_mode):
                _annotation("warning", "Pytest report is not a regular file")
                return None
            payload = report.read(MAX_REPORT_BYTES + 1)
    except OSError:
        _annotation("warning", "Pytest report is unavailable")
        return None
    if len(payload) > MAX_REPORT_BYTES:
        _annotation("warning", "Pytest report exceeds the diagnostic size limit")
        return None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        _annotation("warning", "Pytest report is not UTF-8 XML")
        return None
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        _annotation("warning", "Pytest report contains unsupported XML declarations")
        return None
    return text


def annotate_report(path: str) -> None:
    payload = _read_report(path)
    if payload is None:
        return
    try:
        # Bounded UTF-8 text with all DTD/entity declarations rejected above.
        root = ElementTree.fromstring(payload)  # noqa: S314
    except ElementTree.ParseError:
        _annotation("warning", "Pytest report is invalid XML")
        return
    failures = 0
    for testcase in root.iter("testcase"):
        for failure in testcase:
            if failure.tag not in {"failure", "error"}:
                continue
            failures += 1
            if failures > MAX_FAILURE_ANNOTATIONS:
                continue
            identity = f"{testcase.get('classname', '')}::{testcase.get('name', 'unnamed')}"[:MAX_IDENTITY_CHARACTERS]
            summary = failure.get("message", "")[:MAX_IDENTITY_CHARACTERS]
            detail = (failure.text or "")[-(MAX_MESSAGE_CHARACTERS - len(identity) - len(summary) - 2) :]
            _annotation("error", f"{identity}\n{summary}\n{detail}")
    if failures > MAX_FAILURE_ANNOTATIONS:
        _annotation("warning", f"{failures} pytest failures; first {MAX_FAILURE_ANNOTATIONS} annotated")
    elif failures == 0:
        print("Pytest report contains no failure/error cases")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        annotate_report(sys.argv[1])
    else:
        _annotation("warning", "Expected one pytest report path")
