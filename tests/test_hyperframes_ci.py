"""A successful pytest exit must not hide unexecuted Hyperframes integration."""

from pathlib import Path
import os
import runpy
import subprocess
import sys

import pytest

CHECKER = Path(__file__).resolve().parents[1] / ".github/scripts/check-hyperframes-results.py"
check_results = runpy.run_path(str(CHECKER))["check_results"]


@pytest.mark.parametrize(
    "source,pytest_status,accepted",
    [
        ("def test_one(): pass\ndef test_two(): pass\n", 0, True),
        (
            "import pytest\npytestmark=pytest.mark.skip(reason='CLI unavailable')\ndef test_one(): pass\ndef test_two(): pass\n",
            0,
            False,
        ),
        (
            "import pytest\ndef test_one(): pass\n@pytest.mark.skip(reason='probe failed')\ndef test_two(): pass\n",
            0,
            False,
        ),
        ("def test_one(): pass\ndef test_two(): assert False\n", 1, False),
        ("# No integration cases were collected.\n", 5, False),
        ("def test_one(): pass\n", 0, False),
    ],
    ids=["executed", "all-skipped-green", "mixed-skipped-green", "failed", "empty", "one-case"],
)
def test_real_pytest_junit_requires_executed_success(tmp_path, source, pytest_status, accepted):
    fixture = tmp_path / "test_fixture.py"
    fixture.write_text(source)
    report = tmp_path / "results.xml"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", os.devnull, "-q", str(fixture), f"--junitxml={report}"],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == pytest_status, result.stderr
    if accepted:
        assert check_results(report) == 2
    else:
        with pytest.raises(SystemExit, match="Hyperframes integration report rejected"):
            check_results(report)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"<testsuites>",
        b"\xff",
        b"<!DOCTYPE testsuites [<!ENTITY cases 'anything'>]><testsuites />",
        b"<not-junit />",
        b'<testsuite tests="2" skipped="0" failures="0" errors="0"><testcase /></testsuite>',
        b'<testsuite tests="2" skipped="1" failures="0" errors="0"><testcase /><testcase /></testsuite>',
        b'<testsuite tests="9999999" skipped="0" failures="0" errors="0"><testcase /><testcase /></testsuite>',
        b'<testsuites tests="3" skipped="0" failures="0" errors="0"><testsuite tests="2" skipped="0" failures="0" errors="0"><testcase /><testcase /></testsuite></testsuites>',
        b'<testsuite tests="2" skipped="0" failures="0" errors="0"><testcase /><testcase /><error /></testsuite>',
        b'<testsuite tests="2" skipped="0" failures="0" errors="0"><properties><testcase /><testcase /></properties></testsuite>',
        b"x" * (64 * 1024 + 1),
    ],
)
def test_invalid_or_contradictory_reports_fail_closed(tmp_path, payload):
    report = tmp_path / "results.xml"
    report.write_bytes(payload)
    with pytest.raises(SystemExit, match="Hyperframes integration report rejected"):
        check_results(report)


def test_missing_report_fails_closed(tmp_path):
    with pytest.raises(SystemExit, match="report is unavailable"):
        check_results(tmp_path / "missing.xml")


def test_exact_byte_boundary_and_additional_executed_cases_are_supported(tmp_path):
    report = tmp_path / "results.xml"
    payload = (
        b'<testsuite tests="3" skipped="0" failures="0" errors="0"><testcase /><testcase /><testcase /></testsuite>'
    )
    report.write_bytes(payload + b" " * (64 * 1024 - len(payload)))
    assert check_results(report) == 3


def test_cli_accepts_consistent_executed_cases_and_rejects_missing_report(tmp_path):
    report = tmp_path / "results.xml"
    report.write_text('<testsuite tests="2" skipped="0" failures="0" errors="0"><testcase /><testcase /></testsuite>')
    for path, expected in ((report, 0), (tmp_path / "missing.xml", 1)):
        result = subprocess.run(
            [sys.executable, str(CHECKER), str(path)], capture_output=True, text=True, timeout=5, check=False
        )
        assert result.returncode == expected
        if expected == 0:
            assert "2 executed, zero skipped or unsuccessful" in result.stdout
        else:
            assert "report is unavailable" in result.stderr
