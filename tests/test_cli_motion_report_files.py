"""Report files avoid OS argument limits while retaining bounded admission."""

import json
import subprocess
import sys

import pytest

from kinocut.cli.handlers_motion_acceptance import handle_motion_acceptance_commands
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_CLI_JSON_ARTIFACT_BYTES
from tests.test_motion_acceptance_surfaces import _arguments, _cli_args, _parser


def _file_argv(arguments, path):
    args = _cli_args(arguments)
    argv = ["record-motion-acceptance", args.input_path, "--report-file", str(path)]
    for name in (
        "reviewer_id",
        "source_sha256",
        "report_sha256",
        "watched_intervals_json",
        "dispositions_json",
        "verdict",
    ):
        argv.extend(["--" + name.replace("_", "-"), getattr(args, name)])
    return argv


def test_large_report_file_launches_and_matches_inline_receipt(tmp_path, capsys):
    arguments = _arguments(tmp_path)
    path = tmp_path / "report.json"
    # Valid JSON whitespace makes this exceed Linux's single-argument limit,
    # without changing the report's content hash or human evidence.
    path.write_text(" " * (128 * 1024) + json.dumps(arguments["report"]), encoding="utf-8")
    assert 128 * 1024 < path.stat().st_size < MAX_CLI_JSON_ARTIFACT_BYTES
    assert handle_motion_acceptance_commands(_cli_args(arguments), use_json=True)
    inline = json.loads(capsys.readouterr().out)
    result = subprocess.run(
        [sys.executable, "-m", "kinocut", "--format", "json", *_file_argv(arguments, path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert set(envelope) == {"receipt"}
    assert envelope == inline
    assert envelope["receipt"]["attestation_verified_by_system"] is False


@pytest.mark.parametrize("case", ["oversize", "invalid", "utf8", "deep", "missing"])
def test_bad_report_file_fails_before_review_without_echoing_private_content(tmp_path, monkeypatch, case):
    arguments = _arguments(tmp_path)
    path = tmp_path / "private-report.json"
    if case == "oversize":
        with path.open("wb") as handle:
            handle.truncate(MAX_CLI_JSON_ARTIFACT_BYTES + 1)
    elif case == "invalid":
        path.write_text('{"private-secret":', encoding="utf-8")
    elif case == "utf8":
        path.write_bytes(b"\xffprivate-secret")
    elif case == "deep":
        path.write_text("[" * 129 + "]" * 129, encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid artifact reached motion review")

    monkeypatch.setattr("kinocut.aivideo.inspection.motion_acceptance.record_motion_acceptance", forbidden)
    args = _parser().parse_args(_file_argv(arguments, path))
    with pytest.raises(MCPVideoError) as error:
        handle_motion_acceptance_commands(args, use_json=True)
    assert error.value.error_type == "validation_error"
    assert error.value.code == "invalid_json"
    assert "private" not in str(error.value)


def test_report_input_required_and_mutually_exclusive(tmp_path):
    arguments = _arguments(tmp_path)
    argv = _file_argv(arguments, tmp_path / "report.json")
    for invalid in (argv[:2] + argv[4:], [*argv, "--report-json", "{}"]):
        with pytest.raises(SystemExit) as error:
            _parser().parse_args(invalid)
        assert error.value.code == 2


def test_invalid_file_cli_emits_typed_failure_without_receipt(tmp_path):
    arguments = _arguments(tmp_path)
    path = tmp_path / "private-report.json"
    path.write_text('{"private-secret":', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "kinocut", "--format", "json", *_file_argv(arguments, path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    envelope = json.loads(result.stderr)
    assert envelope["success"] is False
    assert envelope["error"]["type"] == "validation_error"
    assert envelope["error"]["code"] == "invalid_json"
    assert "private" not in result.stderr and "receipt" not in envelope
