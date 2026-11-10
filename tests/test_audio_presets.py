"""Tests for audio preset extraction and configuration."""

import pytest

from mcp_video.audio_engine.presets import get_preset_config, list_presets
from mcp_video.errors import MCPVideoError


class TestPresetConfig:
    def test_list_presets_returns_sorted_names(self):
        names = list_presets()
        assert isinstance(names, list)
        assert names == sorted(names)
        assert "ui-blip" in names
        assert "drone-low" in names

    def test_get_preset_config_returns_copy(self):
        cfg1 = get_preset_config("ui-blip")
        cfg2 = get_preset_config("ui-blip")
        assert cfg1 == cfg2
        assert cfg1 is not cfg2  # deep copy
        cfg1["volume"] = 999
        assert get_preset_config("ui-blip")["volume"] != 999

    def test_get_preset_config_unknown_raises(self):
        # The refusal is the package's own error type, it carries the
        # shipped guidance, and it does not repeat the refused name.
        with pytest.raises(MCPVideoError) as exc:
            get_preset_config("not-a-real-preset")
        assert exc.value.error_type == "validation_error"
        assert exc.value.code == "invalid_parameter"
        assert "Unknown preset" in str(exc.value)
        assert "ui-blip" in str(exc.value)
        assert "not-a-real-preset" not in str(exc.value)


class TestAudioPresetOrchestration:
    def test_audio_preset_unknown_raises_mcpvideoerror(self, tmp_path):
        output = str(tmp_path / "out.wav")
        with pytest.raises(MCPVideoError) as exc:
            from mcp_video.audio_engine.synthesis import audio_preset

            audio_preset("not-a-real-preset", output)
        assert "Unknown preset" in str(exc.value)

    def test_pitch_multiplier_low(self, tmp_path):
        output = str(tmp_path / "out.wav")
        from mcp_video.audio_engine.synthesis import audio_preset

        result = audio_preset("ui-blip", output, pitch="low")
        assert result == output

    def test_pitch_multiplier_high(self, tmp_path):
        output = str(tmp_path / "out.wav")
        from mcp_video.audio_engine.synthesis import audio_preset

        result = audio_preset("ui-blip", output, pitch="high")
        assert result == output

    def test_unknown_pitch_rejected(self, tmp_path):
        output = str(tmp_path / "out.wav")
        from mcp_video.audio_engine.synthesis import audio_preset

        with pytest.raises(MCPVideoError, match="pitch"):
            audio_preset("ui-blip", output, pitch="bass")

    def test_invalid_intensity_rejected(self, tmp_path):
        output = str(tmp_path / "out.wav")
        from mcp_video.audio_engine.synthesis import audio_preset

        with pytest.raises(MCPVideoError, match="intensity"):
            audio_preset("typing", output, intensity=2.0)

    def test_duration_override(self, tmp_path):
        output = str(tmp_path / "out.wav")
        from mcp_video.audio_engine.synthesis import audio_preset

        result = audio_preset("ui-blip", output, duration=2.0)
        assert result == output

    def test_intensity_scales_typing_volume(self, tmp_path):
        output = str(tmp_path / "out.wav")
        from mcp_video.audio_engine.synthesis import audio_preset

        result = audio_preset("typing", output, intensity=1.0)
        assert result == output

    def test_drone_ominous_preset(self, tmp_path):
        output = str(tmp_path / "out.wav")
        from mcp_video.audio_engine.synthesis import audio_preset

        result = audio_preset("drone-ominous", output, duration=2.0)
        assert result == output
