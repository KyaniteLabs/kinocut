"""A submitted value must never reach the error text the caller receives.

The retry invocation names the arguments so an operator knows what to fix.
The values themselves are the caller's data — a nested job spec can carry a
credential — so they are named by type, never repeated.
"""

from __future__ import annotations

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
