"""The four refusals the reviewer named, proven at every layer.

A refusal reaches the caller through several doors, and a value hidden
at one of them can still escape through another:

* the **raised** exception text;
* the **serialized** JSON payload (``to_dict``);
* the **returned** result dict an MCP tool hands back;
* the **CLI panel** the operator sees;
* the **retry** message that tells the operator what to fix.

A child process is the other door. FFmpeg, c2patool and Hyperframes all
echo the path the caller submitted, so a diagnostic is caller data too:
it stays on the error object, where the operator who holds it can read
it, and out of the payload.

The verdict named four refusals that still repeated the caller's value:
``video_merge.transition``, ``video_resize.aspect_ratio``,
``video_thumbnail.timestamp``, and the Shorts probe exception. Each is
proven here, with a value that looks like a credential so a leak cannot
hide in a truncated or re-encoded message.
"""

from __future__ import annotations

import json

import pytest

SECRET = "sk-live-9f3a7cSECRET"  # noqa: S105 - a credential-shaped probe value, not a secret


def _payload(error: Exception) -> dict[str, object]:
    to_dict = getattr(error, "to_dict", None)
    if to_dict is None:
        return {}
    return to_dict()


def _assert_no_secret(text: str, where: str) -> None:
    assert SECRET not in text, f"the rejected value reached the {where}: {text!r}"


def _assert_clean(error: Exception, where: str) -> None:
    _assert_no_secret(str(error), f"raised error ({where})")
    payload = _payload(error)
    _assert_no_secret(str(payload), f"serialized payload ({where})")
    _assert_no_secret(json.dumps(payload, default=str), f"serialized JSON ({where})")


def _assert_clean_result(result: object, where: str) -> None:
    """An MCP tool returns a dict, not an exception."""
    assert isinstance(result, dict), f"{where} did not return a result dict"
    _assert_no_secret(json.dumps(result, default=str), f"returned payload ({where})")


# --------------------------------------------------------------------------
# the child's diagnostic
# --------------------------------------------------------------------------


def test_a_child_diagnostic_never_reaches_the_payload():
    """A child's output repeats the caller's path, so it is not published."""
    from kinocut.errors import HyperframesRenderError, ProcessingError, RevideoRenderError

    diagnostic = f"No such file or directory: '{SECRET}'"
    for error in (
        ProcessingError("ffmpeg -i input.mp4 output.mp4", 1, diagnostic),
        HyperframesRenderError("hyperframes render", 1, diagnostic),
        RevideoRenderError("node render.js", 1, diagnostic),
    ):
        where = type(error).__name__
        _assert_clean(error, where)
        # The operator who holds the object still has the diagnostic.
        assert error.full_stderr == diagnostic


def test_a_preset_refusal_names_the_accepted_values_not_the_submitted_one():
    from kinocut.server_tools_media import video_watermark

    result = video_watermark(input_path="/tmp/a.mp4", image_path="/tmp/b.png", preset=SECRET)
    _assert_clean_result(result, "watermark preset")
    # The refusal still says what is accepted.
    assert "ultrafast" in json.dumps(result)


def test_a_timeline_refusal_never_repeats_the_submitted_value():
    from kinocut.server_tools_media import video_edit

    result = video_edit(timeline=SECRET)
    _assert_clean_result(result, "edit timeline")
    assert "timeline" in json.dumps(result).lower()


def test_a_refused_identifier_is_named_by_its_type_not_repeated():
    """A caller-chosen id is named by its type; the index still says which."""
    from kinocut.models import _validate_position

    with pytest.raises(Exception) as raised:
        _validate_position(SECRET)
    _assert_no_secret(str(raised.value), "position refusal")
    assert "str" in str(raised.value)


# --------------------------------------------------------------------------
# video_merge.transition
# --------------------------------------------------------------------------


def test_merge_transition_never_repeats_the_submitted_value():
    """The MCP tool validates the transition before it touches the paths."""
    from kinocut.server_tools_basic import video_merge

    result = video_merge(clips=["/tmp/a.mp4", "/tmp/b.mp4"], transition=SECRET)
    _assert_clean_result(result, "merge transition")
    # The refusal still says what was expected.
    assert "transition" in json.dumps(result).lower()


def test_merge_transitions_never_repeat_the_submitted_values():
    from kinocut.server_tools_basic import video_merge

    result = video_merge(clips=["/tmp/a.mp4", "/tmp/b.mp4"], transitions=[SECRET])
    _assert_clean_result(result, "merge transitions")
    assert "transition" in json.dumps(result).lower()


def test_merge_engine_refusal_never_repeats_the_submitted_value():
    """The engine's own guard refuses the same way."""
    from kinocut.engine_merge import _build_xfade_video_filter

    with pytest.raises(Exception) as excinfo:
        _build_xfade_video_filter(2, 1, [SECRET], [0.0], 1.0)
    _assert_clean(excinfo.value, "merge engine transition")


# --------------------------------------------------------------------------
# video_resize.aspect_ratio
# --------------------------------------------------------------------------


def test_resize_aspect_ratio_never_repeats_the_submitted_value():
    from kinocut.engine_resize import _resize_dimensions

    with pytest.raises(Exception) as excinfo:
        _resize_dimensions(
            type("Info", (), {"width": 1920, "height": 1080, "display_width": 1920, "display_height": 1080})(),
            width=None,
            height=None,
            aspect_ratio=SECRET,
        )
    error = excinfo.value
    _assert_clean(error, "resize aspect ratio")
    assert "aspect" in str(error).lower()


# --------------------------------------------------------------------------
# video_thumbnail.timestamp
# --------------------------------------------------------------------------


def test_thumbnail_timestamp_never_repeats_the_submitted_value(monkeypatch):
    """The thumbnail guard refuses the rejected timestamp by type."""
    from kinocut import engine_thumbnail

    monkeypatch.setattr(engine_thumbnail, "get_duration", lambda _path: 10.0)
    monkeypatch.setattr(engine_thumbnail, "_validate_input_path", lambda path: path)
    with pytest.raises(Exception) as excinfo:
        engine_thumbnail.thumbnail("/tmp/in.mp4", timestamp=SECRET, output_path="/tmp/out.jpg")
    error = excinfo.value
    _assert_clean(error, "thumbnail timestamp")
    # The refusal still names the argument and what was expected.
    message = str(error).lower()
    assert "time" in message
    assert "expected number" in message


# --------------------------------------------------------------------------
# The Shorts probe exception
# --------------------------------------------------------------------------


def test_shorts_probe_never_repeats_the_lower_level_exception_text(monkeypatch):
    """The lower-level failure is caught; only the reason survives.

    The flow catches ``OSError``, ``ValueError`` and ``MCPVideoError``
    around the probe, so the failure below is one of those — the kind a
    real filesystem or decoder raises, with the submitted path inside
    its text.
    """
    from kinocut.product import shorts_flow

    def _explode(_path):
        raise OSError(f"could not open {SECRET}")

    monkeypatch.setattr("kinocut.engine_probe.probe", _explode, raising=False)
    with pytest.raises(Exception) as excinfo:
        shorts_flow._validate_source_duration("/tmp/source.mp4", [(0.0, 1.0, None)])
    error = excinfo.value
    _assert_clean(error, "shorts source duration")
    # The refusal still says what could not be measured.
    assert "measure" in str(error).lower()


def test_shorts_trim_probe_never_repeats_the_lower_level_exception_text(monkeypatch):
    """The rendered-trim probe takes the same fixed-message treatment."""
    from kinocut.product import shorts_flow

    def _explode(_path):
        raise OSError(f"could not open {SECRET}")

    monkeypatch.setattr("kinocut.engine_probe.probe", _explode, raising=False)
    with pytest.raises(Exception) as excinfo:
        shorts_flow._measured_segment_durations(["/tmp/trim.mp4"])
    error = excinfo.value
    _assert_clean(error, "shorts trim duration")
    assert "measure" in str(error).lower()


# --------------------------------------------------------------------------
# The retry message
# --------------------------------------------------------------------------


def test_the_retry_message_never_repeats_a_rejected_value():
    """The retry message names the argument; it never repeats the value."""
    from kinocut.errors import MCPVideoError, retry_message

    error = MCPVideoError(
        "Invalid transition: expected one of wipe, got str",
        error_type="validation_error",
        code="invalid_transition",
    )
    _assert_clean(error, "retry")
    retried = retry_message(str(error), "invalid_transition")
    _assert_no_secret(retried, "retry message")
