"""A submitted value must never reach the error text the caller receives.

The retry invocation names the arguments so an operator knows what to fix.
The values themselves are the caller's data — a nested job spec can carry a
credential — so they are named by type, never repeated.
"""

from __future__ import annotations

import json

import pytest

from kinocut.errors import MCPVideoError, ValidationError
from kinocut.revideo_engine import _validate_job


def test_a_rejected_nested_value_never_reaches_the_error_text():
    submitted_value = "sk-live-DO-NOT-ECHO-9f2b7c"
    with pytest.raises(ValidationError) as excinfo:
        _validate_job({"width": submitted_value})
    error = excinfo.value
    assert submitted_value not in str(error)
    payload = error.to_dict()
    assert submitted_value not in payload["message"]
    assert submitted_value not in str(payload.get("suggested_action", ""))


def test_a_rejected_number_is_still_reported():
    # A number is not a secret, and the operator needs it to fix the call.
    with pytest.raises(ValidationError) as excinfo:
        _validate_job({"width": 999999})
    assert "999999" in str(excinfo.value)


def test_the_suggested_action_is_bounded_before_it_leaves_the_process():
    error = MCPVideoError(
        "boom",
        error_type="validation_error",
        code="invalid_argument",
        suggested_action={"description": "x" * 5000, "tool": "video_trim"},
    )
    action = error.to_dict()["suggested_action"]
    assert len(action["description"]) < 5000
    assert action["tool"] == "video_trim"


def test_a_shipped_advisory_survives_the_action_sanitiser_intact():
    # The action budget must not eat the words that say what to change.
    description = (
        "FFmpeg did not recognize the requested encoder 'LIBX265'. "
        "Check the exact component name and selected build's support, "
        "or explicitly choose a compatible operation. "
        "Kinocut has not changed the requested codec or filters."
    )
    error = MCPVideoError(
        "FFmpeg did not recognize the requested encoder 'LIBX265'.",
        error_type="dependency_error",
        code="unknown_encoder",
        suggested_action={"auto_fix": False, "description": description},
    )
    cleaned = error.to_dict()["suggested_action"]["description"]
    assert "exact component name" in cleaned
    assert "truncated" not in cleaned
    assert cleaned == description


def test_a_rejected_out_file_is_never_echoed():
    # The output filename is the caller's data too.
    submitted_value = "«redacted:sk-…»"
    with pytest.raises(ValidationError) as excinfo:
        _validate_job({"out_file": submitted_value})
    error = excinfo.value
    assert submitted_value not in str(error)
    assert submitted_value not in error.to_dict()["message"]


def test_a_rejected_trim_time_is_never_echoed():
    # The trim validator used to quote the rejected value back.
    from kinocut.engine_edit import _validate_trim_times

    submitted_value = "«redacted:sk-…»"
    with pytest.raises(MCPVideoError) as excinfo:
        _validate_trim_times(submitted_value, None, None)
    error = excinfo.value
    assert submitted_value not in str(error)
    assert submitted_value not in error.to_dict()["message"]
    assert "start" in error.to_dict()["message"]


def test_the_generic_error_constructors_never_echo_a_submitted_value():
    # A path, a codec and a project path are all caller-controlled strings.
    from kinocut.errors import CodecError, HyperframesProjectError, InputFileError

    submitted_value = "«redacted:sk-…»"
    errors = [
        InputFileError(submitted_value, reason=f"no such file: {submitted_value}"),
        CodecError(submitted_value, detail=f"the codec {submitted_value} is not supported"),
        HyperframesProjectError(submitted_value, reason=f"invalid project: {submitted_value}"),
    ]
    for error in errors:
        assert submitted_value not in str(error), type(error).__name__
        assert submitted_value not in error.to_dict()["message"], type(error).__name__
        assert submitted_value not in str(error.to_dict()["suggested_action"]), type(error).__name__


def test_a_rejected_codec_still_says_what_to_do():
    from kinocut.errors import CodecError

    error = CodecError("hevc", detail="the codec hevc is not supported")
    assert "hevc" not in str(error)
    assert "H.264" in str(error.to_dict()["suggested_action"])


# The output-path guards are the same class: a path in an error message is a
# path in a log, a transcript and a screenshot. The condition is enough to
# act on; the value adds exposure and nothing else.

CALLER_FILE_NAME = "secret-media-9f3a7c.mp4"


@pytest.fixture
def isolated_operation():
    from kinocut.ffmpeg_helpers import _reset_operation_inputs

    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


def _serialized(exc: MCPVideoError) -> str:
    """The payload the MCP server and the CLI hand to the caller."""
    return json.dumps(exc.to_dict(), default=str)


def _assert_absent(exc: MCPVideoError, secret: str) -> None:
    """A submitted value is absent from every layer the caller can see."""
    assert secret not in str(exc)
    assert secret not in _serialized(exc)


def test_the_alias_guard_does_not_repeat_the_path(tmp_path, isolated_operation):
    from kinocut.ffmpeg_helpers import _reject_self_overwrite, _validate_input_path

    source = tmp_path / CALLER_FILE_NAME
    source.write_bytes(b"input")
    _validate_input_path(str(source))
    with pytest.raises(MCPVideoError) as raised:
        _reject_self_overwrite(str(source))
    _assert_absent(raised.value, str(source))
    assert "aliases an input" in str(raised.value)


def test_the_existing_output_guard_does_not_repeat_the_path(tmp_path, isolated_operation):
    from kinocut.ffmpeg_helpers import _validate_write_path

    existing = tmp_path / CALLER_FILE_NAME
    existing.write_bytes(b"prior")
    with pytest.raises(MCPVideoError) as raised:
        _validate_write_path(
            str(existing),
            allowed_existing_suffixes=frozenset({".mp4"}),
            label="Output path",
        )
    _assert_absent(raised.value, str(existing))
    assert "already exists" in str(raised.value)


def test_the_unsafe_path_guard_does_not_repeat_the_path(tmp_path, isolated_operation):
    from kinocut.ffmpeg_helpers import _validate_artifact_location

    unsafe = f"{tmp_path}/{CALLER_FILE_NAME}/../{CALLER_FILE_NAME}"
    with pytest.raises(MCPVideoError) as raised:
        _validate_artifact_location(unsafe, "Output path")
    _assert_absent(raised.value, unsafe)
    assert CALLER_FILE_NAME not in str(raised.value)
    assert "directory traversal" in str(raised.value)


def test_the_cli_panel_does_not_repeat_the_path(tmp_path, capfd, monkeypatch, isolated_operation):
    from kinocut.cli.formatting import _format_error
    from kinocut.ffmpeg_helpers import _validate_artifact_location

    monkeypatch.setenv("COLUMNS", "240")
    unsafe = f"{tmp_path}/{CALLER_FILE_NAME}/../{CALLER_FILE_NAME}"
    with pytest.raises(MCPVideoError) as raised:
        _validate_artifact_location(unsafe, "Output path")
    _format_error(raised.value)
    captured = capfd.readouterr()
    output = captured.out + captured.err
    assert CALLER_FILE_NAME not in output
    # The message was rendered, so the absence above is not a blank panel.
    assert "directory traversal" in output


def test_the_retry_message_does_not_repeat_the_path(tmp_path, isolated_operation):
    from kinocut.errors import retry_message
    from kinocut.ffmpeg_helpers import _validate_artifact_location

    unsafe = f"{tmp_path}/{CALLER_FILE_NAME}/../{CALLER_FILE_NAME}"
    with pytest.raises(MCPVideoError) as raised:
        _validate_artifact_location(unsafe, "Output path")
    retry = retry_message(str(raised.value), getattr(raised.value, "code", "unknown"))
    assert CALLER_FILE_NAME not in retry
