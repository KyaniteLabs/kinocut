"""A refusal must carry an invocation the operator can actually re-run.

The retry context binds the tool and the arguments that were submitted. The
invocation has to name them: "with corrected parameters" on its own does not
say which tool was called or with what, and the stored arguments existed for
exactly that (t_e3775201 F5).
"""

from kinocut.errors import MCPVideoError, retry_context


def _message(**arguments) -> str:
    with retry_context("video_trim", arguments):
        return MCPVideoError("boom", code="invalid_parameter").to_dict()["message"]


def test_retry_invocation_names_the_tool_and_the_submitted_arguments():
    message = _message(input_path="/tmp/a.mp4", start=0, end=2)
    assert "video_trim" in message
    assert "input_path" in message
    assert "start" in message
    assert "end" in message


def test_retry_invocation_never_echoes_submitted_values():
    """A validation error must not echo the value it just rejected."""
    message = _message(api_key="s3cret-value", target="youtube")
    assert "s3cret-value" not in message
    assert "youtube" not in message
    assert "api_key" in message
    assert "target" in message


def test_retry_invocation_does_not_echo_long_values():
    message = _message(prompt="x" * 500)
    assert "x" * 500 not in message


def test_retry_invocation_stays_silent_without_a_context():
    message = MCPVideoError("boom", code="invalid_parameter").to_dict()["message"]
    assert "submitted:" not in message


def test_retry_invocation_carries_typed_placeholders():
    """F5: the retry is a replayable invocation — names AND types, no values."""
    message = _message(api_key="s3cret-value", count=3)
    assert "api_key=<str>" in message
    assert "count=<int>" in message
    assert "s3cret-value" not in message


def test_retry_invocation_names_the_cli_command_for_mapped_tools():
    with retry_context("video_quality_check", {"input_path": "/tmp/a.mp4"}):
        message = MCPVideoError("boom", code="invalid_parameter").to_dict()["message"]
    assert "video-quality-check" in message
