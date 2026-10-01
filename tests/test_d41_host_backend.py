"""Host capability probing must use the configured engine binary resolver."""

import shutil
import subprocess
from unittest.mock import Mock

import pytest

from kinocut import engine_runtime_utils
from kinocut.sound_joins.d41_bind import KinocutBedAdapter


@pytest.fixture
def configured_binaries(monkeypatch):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg required")
    monkeypatch.setenv("KINOCUT_FFMPEG_EXECUTABLE", ffmpeg)
    monkeypatch.setenv("KINOCUT_FFPROBE_EXECUTABLE", ffprobe)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(engine_runtime_utils, "_FFMPEG", "")
    monkeypatch.setattr(engine_runtime_utils, "_FFPROBE", "")
    monkeypatch.setattr(engine_runtime_utils, "_AVAILABLE_FILTERS", None)
    return ffmpeg, ffprobe


def test_real_configured_binaries_available_without_path(configured_binaries):
    assert KinocutBedAdapter().probe().available
    assert engine_runtime_utils._ffmpeg() == configured_binaries[0]
    assert engine_runtime_utils._ffprobe() == configured_binaries[1]


@pytest.mark.parametrize("name", ["KINOCUT_FFMPEG_EXECUTABLE", "KINOCUT_FFPROBE_EXECUTABLE"])
def test_invalid_configured_binary_is_unavailable(configured_binaries, monkeypatch, tmp_path, name):
    monkeypatch.setenv(name, str(tmp_path / "nonexistent"))
    result = KinocutBedAdapter().probe()
    assert not result.available
    assert result.reason_code == "d41_audio_bed_unavailable"


def test_missing_required_filter_is_unavailable(configured_binaries, monkeypatch):
    check = Mock(side_effect=[True, False])
    monkeypatch.setattr(engine_runtime_utils, "_check_filter_available", check)
    assert not KinocutBedAdapter().probe().available
    assert [call.args[0] for call in check.call_args_list] == ["sidechaincompress", "loudnorm"]


@pytest.mark.parametrize("failure", [OSError("cannot execute"), subprocess.TimeoutExpired("ffmpeg", 10)])
def test_filter_backend_probe_failure_is_unavailable(configured_binaries, monkeypatch, failure):
    monkeypatch.setattr(engine_runtime_utils, "_check_filter_available", Mock(side_effect=failure))
    assert not KinocutBedAdapter().probe().available
