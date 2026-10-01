"""Changes to central CI policy must change the executable result guard."""

from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from kinocut import limits, validation

CHECKER = Path(__file__).resolve().parents[1] / ".github/scripts/check-hyperframes-results.py"


def _report(path, cases):
    payload = (
        f'<testsuite tests="{cases}" skipped="0" failures="0" errors="0">' + "<testcase />" * cases + "</testsuite>"
    ).encode()
    path.write_bytes(payload)
    return payload


@pytest.mark.parametrize("over_limit", [False, True])
def test_checker_reads_byte_ceiling_from_shared_policy(tmp_path, monkeypatch, over_limit):
    report = tmp_path / "results.xml"
    payload = _report(report, 2)
    monkeypatch.setattr(limits, "MAX_CI_HYPERFRAMES_REPORT_BYTES", len(payload) - int(over_limit))
    check_results = runpy.run_path(str(CHECKER))["check_results"]
    if over_limit:
        with pytest.raises(SystemExit, match="report exceeds its byte limit"):
            check_results(report)
    else:
        assert check_results(report) == 2


@pytest.mark.parametrize("minimum,cases,accepted", [(1, 1, True), (3, 2, False), (3, 3, True)])
def test_checker_uses_central_execution_minimum(tmp_path, monkeypatch, minimum, cases, accepted):
    report = tmp_path / "results.xml"
    _report(report, cases)
    monkeypatch.setattr(validation, "MIN_CI_HYPERFRAMES_EXECUTED_CASES", minimum)
    check_results = runpy.run_path(str(CHECKER))["check_results"]
    if accepted:
        assert check_results(report) == cases
    else:
        with pytest.raises(SystemExit, match=f"fewer than {minimum} tests executed"):
            check_results(report)


def test_installed_checker_cli_resolves_policy_outside_checkout(tmp_path):
    report = tmp_path / "results.xml"
    _report(report, 2)
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(report)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "2 executed, zero skipped or unsuccessful" in result.stdout
