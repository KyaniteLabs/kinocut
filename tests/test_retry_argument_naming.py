"""Every refusal path names the arguments the call carried — and never their values.

The retry invocation has to tell the operator which parameters to change.
It must not repeat what was submitted: a rejected value can be anything the
caller sent, including a credential.
"""

from __future__ import annotations

import pytest

from kinocut.errors import MCPVideoError, retry_context


@pytest.mark.parametrize(
    ("code", "mcp_token", "cli_token"),
    [
        ("output_exists", "overwrite=true", "--overwrite"),
        ("overwrite_refused", "overwrite=true", "--overwrite"),
        ("unsafe_path", "a new output_path", "--output <new-media-path>"),
        ("invalid_output_path", "a new output_path", "--output <new-media-path>"),
    ],
)
def test_special_retry_codes_name_the_submitted_arguments(code, mcp_token, cli_token):
    with retry_context("video_trim", {"input_path": "in.mp4", "output_path": "out.mp4"}):
        message = MCPVideoError("refused", error_type="validation_error", code=code).to_dict()["message"]
    # Both halves name the arguments the call carried...
    assert mcp_token in message
    assert cli_token in message
    assert "input_path" in message
    assert "output_path" in message
    # ...and never the values that were submitted.
    assert "in.mp4" not in message
    assert "out.mp4" not in message


def test_the_generic_path_keeps_the_established_cli_phrase_and_names_the_arguments():
    with retry_context("video_trim", {"input_path": "in.mp4"}):
        message = MCPVideoError("refused", error_type="validation_error", code="invalid_argument").to_dict()["message"]
    assert "run kino trim with corrected flags" in message
    assert "input_path" in message
    assert "in.mp4" not in message


def test_a_refusal_without_a_context_still_carries_its_tokens():
    message = MCPVideoError("refused", error_type="validation_error", code="output_exists").to_dict()["message"]
    assert "overwrite=true" in message
    assert "--overwrite" in message
