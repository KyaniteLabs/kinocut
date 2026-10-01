"""A successful pytest exit must not hide unexecuted Hyperframes integration."""

from pathlib import Path
import os
import re
import runpy
import shutil
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


@pytest.mark.parametrize("workflow_name", ["ci.yml", "pr-safety.yml"])
@pytest.mark.parametrize(
    "changed,requires_code",
    [
        (".github/scripts/check-hyperframes-results.py", True),
        (".github/workflows/ci.yml", True),
        ("tests/test_hyperframes_ci.py", True),
        ("kinocut/hyperframes_engine.py", True),
        ("kinocut_sound/defaults.py", True),
        ("mcp_video.py", True),
        ("docs/research/hyperframes-ci-followup/README.md", False),
        ("CHANGELOG.md", False),
        ("CHANGELOG.md\n.github/scripts/check-hyperframes-results.py", True),
    ],
)
def test_actual_ci_code_classifier_covers_hyperframes_gate_changes(workflow_name, changed, requires_code):
    grep = shutil.which("grep")
    if grep is None and os.name == "nt":
        pytest.skip("GitHub POSIX change classification requires grep")
    assert grep is not None
    workflow = (CHECKER.parents[1] / "workflows" / workflow_name).read_text()
    expression = re.search(r"grep -Eq '([^']+)'", workflow)
    assert expression is not None, "actual CI code-classification expression is unavailable"
    result = subprocess.run(
        [grep, "-Eq", expression.group(1)],
        input=changed + "\n",
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == (0 if requires_code else 1), result.stderr


@pytest.mark.parametrize(
    "first,code,docker",
    [
        (".github/scripts/check-hyperframes-results.py", True, False),
        ("mcp_video.py", True, True),
        (None, False, False),
    ],
)
def test_actual_ci_conditions_preserve_early_matches_under_pipefail(first, code, docker):
    bash = shutil.which("bash")
    if bash is None and os.name == "nt":
        pytest.skip("GitHub POSIX change classification requires bash")
    assert bash is not None
    workflow = (CHECKER.parents[1] / "workflows/ci.yml").read_text()
    classifier = workflow.split("  changes:", 1)[1].split("  repository-readiness:", 1)[0]
    conditions = [
        line.strip() for line in classifier.splitlines() if line.strip().startswith("if ") and "grep -Eq" in line
    ]
    assert len(conditions) == 2
    paths = ([first] if first else []) + [f"docs/research/{'x' * 100}/receipt-{index:04d}.md" for index in range(500)]
    changed = "\n".join(paths)
    changed += "\ndocs/" + "x" * (67544 - len(changed.encode()) - 6)
    assert len(changed.encode()) == 67544
    script = "\n".join(
        f"{condition}\nprintf '{name}=true\\n'\nelse\nprintf '{name}=false\\n'\nfi"
        for name, condition in zip(("code", "docker"), conditions, strict=True)
    )
    # The original broken pipeline depended on producer/reader scheduling.
    for _ in range(5):
        result = subprocess.run(
            [bash, "-euo", "pipefail", "-c", script],
            env={**os.environ, "changed": changed},
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [f"code={str(code).lower()}", f"docker={str(docker).lower()}"]


@pytest.mark.parametrize(
    "first,requires_code",
    [(".github/scripts/check-hyperframes-results.py", True), ("mcp_video.py", True), (None, False)],
)
def test_actual_pr_condition_preserves_early_matches_under_pipefail(first, requires_code):
    bash = shutil.which("bash")
    if bash is None and os.name == "nt":
        pytest.skip("GitHub POSIX change classification requires bash")
    assert bash is not None
    workflow = (CHECKER.parents[1] / "workflows/pr-safety.yml").read_text()
    conditions = [
        line.strip() for line in workflow.splitlines() if line.strip().startswith("if ") and "grep -Eq" in line
    ]
    assert len(conditions) == 1
    paths = ([first] if first else []) + [f"docs/research/{'x' * 100}/receipt-{index:04d}.md" for index in range(500)]
    changed = "\n".join(paths)
    script = f"{conditions[0]}\nprintf 'code=true\\n'\nelse\nprintf 'code=false\\n'\nfi"
    for _ in range(5):
        result = subprocess.run(
            [bash, "-euo", "pipefail", "-c", script],
            env={**os.environ, "changed": changed},
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"code={str(requires_code).lower()}"
