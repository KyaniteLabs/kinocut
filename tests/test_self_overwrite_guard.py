"""Regression tests: an output may not alias an input of the same operation.

An agent passing ``output_path == input_path`` used to get a silent in-place
overwrite that destroyed its source file mid-render. The central write guard
now rejects any output that resolves to a path already read as an input of
the current operation — resolved-path compare, not string-level — with the
same structured ``invalid_output_path`` error the other write guardrails use.
"""

import contextvars
import hashlib
import os
import sys

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.ffmpeg_helpers import (
    _reset_operation_inputs,
    _validate_input_path,
    _validate_output_path,
)


@pytest.fixture(autouse=True)
def _fresh_operation_scope():
    """Keep each test's operation scope isolated from its neighbours."""
    _reset_operation_inputs()
    yield
    _reset_operation_inputs()


def _file_digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class TestValidateWritePathAliasGuard:
    def test_output_equal_to_input_is_rejected(self, tmp_path):
        src = tmp_path / "base.mp4"
        src.write_bytes(b"payload")

        _validate_input_path(str(src))

        with pytest.raises(MCPVideoError) as exc:
            _validate_output_path(str(src))
        assert exc.value.code == "invalid_output_path"
        assert exc.value.error_type == "validation_error"
        assert "aliases an input" in str(exc.value)

    def test_alias_compare_is_resolved_path_not_string_level(self, tmp_path):
        src = tmp_path / "base.mp4"
        src.write_bytes(b"payload")
        # A different spelling that resolves to the same file; a string-level
        # compare would let it through.
        aliased = os.path.join(str(tmp_path), ".", "base.mp4")

        _validate_input_path(str(src))

        with pytest.raises(MCPVideoError) as exc:
            _validate_output_path(aliased)
        assert exc.value.code == "invalid_output_path"

    @pytest.mark.skipif(sys.platform == "win32", reason="hardlinks via os.link are POSIX-reliable here")
    def test_hardlinked_output_is_rejected(self, tmp_path):
        src = tmp_path / "base.mp4"
        src.write_bytes(b"payload")
        link = tmp_path / "link.mp4"
        os.link(src, link)

        _validate_input_path(str(src))

        with pytest.raises(MCPVideoError) as exc:
            _validate_output_path(str(link))
        assert exc.value.code == "invalid_output_path"

    def test_unrelated_output_still_allowed(self, tmp_path):
        src = tmp_path / "base.mp4"
        src.write_bytes(b"payload")
        out = tmp_path / "out.mp4"
        out.write_bytes(b"previous render")

        _validate_input_path(str(src))

        # Media-suffix overwrite of an unrelated file remains permitted.
        assert _validate_output_path(str(out)) == str(out)

    def test_scope_does_not_leak_between_contexts(self, tmp_path):
        # Each MCP tool call runs in its own context copy; an input read in
        # one operation must not poison a later operation's writes.
        src = tmp_path / "base.mp4"
        src.write_bytes(b"payload")

        def record():
            _validate_input_path(str(src))

        contextvars.copy_context().run(record)

        # Fresh context: writing to src now is a plain overwrite decision,
        # not an alias rejection.
        assert _validate_output_path(str(src)) == str(src)


class TestSelfOverwriteRegression:
    def test_trim_self_overwrite_is_blocked_and_input_survives(self, sample_video):
        from mcp_video.engine_edit import trim

        before_digest = _file_digest(sample_video)
        before_size = os.path.getsize(sample_video)

        with pytest.raises(MCPVideoError) as exc:
            trim(sample_video, start="0", duration="0.4", output_path=sample_video)

        assert exc.value.code == "invalid_output_path"
        assert os.path.getsize(sample_video) == before_size
        assert _file_digest(sample_video) == before_digest

    def test_trim_to_distinct_output_still_renders(self, sample_video, tmp_path):
        from mcp_video.engine_edit import trim

        out = str(tmp_path / "cut.mp4")
        result = trim(sample_video, start="0", duration="0.4", output_path=out)
        assert os.path.isfile(result.output_path)

    def test_server_tool_returns_structured_error_and_input_survives(self, sample_video):
        from mcp_video.server import video_trim

        before_digest = _file_digest(sample_video)

        result = video_trim(sample_video, start="0", duration="0.4", output_path=sample_video)

        assert result["success"] is False
        assert result["error"]["code"] == "invalid_output_path"
        assert result["error"]["type"] == "validation_error"
        assert _file_digest(sample_video) == before_digest
