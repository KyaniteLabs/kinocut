"""Regression tests for the manual BasicPitch integration boundary."""

from __future__ import annotations

import pytest

from mcp_video.audio_engine.integrations.basic_pitch_bridge import detect_pitch
from mcp_video.errors import MCPVideoError


def test_detect_pitch_missing_dependency_uses_manual_install_hint(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"")

    with pytest.raises(MCPVideoError) as exc_info:
        detect_pitch(str(audio))

    error = exc_info.value
    assert error.code == "basic_pitch_not_found"
    assert "manual optional integration" in str(error)
    assert "Python 3.11 or 3.12" in str(error)
