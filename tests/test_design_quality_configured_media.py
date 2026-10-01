"""Design guardrails honor configured media tools without relying on PATH."""

import shutil
import subprocess
from unittest.mock import Mock

import pytest

from kinocut import engine_runtime_utils, ffmpeg_helpers
from kinocut.design_quality.guardrails import DesignQualityGuardrails
from kinocut.errors import FFprobeNotFoundError, InputFileError, ProcessingError


@pytest.fixture
def configured_media(monkeypatch):
    binaries = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")}
    if not all(binaries.values()):
        pytest.skip("FFmpeg and FFprobe required")
    monkeypatch.setenv("KINOCUT_FFMPEG_EXECUTABLE", binaries["ffmpeg"])
    monkeypatch.setenv("KINOCUT_FFPROBE_EXECUTABLE", binaries["ffprobe"])
    monkeypatch.setattr(engine_runtime_utils, "_FFMPEG", "")
    monkeypatch.setattr(engine_runtime_utils, "_FFPROBE", "")
    monkeypatch.setenv("PATH", "")
    return binaries


@pytest.mark.parametrize("with_audio", [False, True])
def test_design_analysis_uses_configured_tools_with_empty_path(configured_media, tmp_path, monkeypatch, with_audio):
    source = tmp_path / "configured.mp4"
    cmd = [
        configured_media["ffmpeg"],
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=64x64:r=30:d=0.5",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "mpeg4", str(source)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)

    run = Mock(wraps=subprocess.run)
    monkeypatch.setattr(ffmpeg_helpers.subprocess, "run", run)
    guardrails = DesignQualityGuardrails()
    report = guardrails.analyze(str(source))

    assert report.video_path == str(source)
    assert 0 <= report.overall_score <= 100
    assert guardrails._probe_video(str(source))["width"] == 64
    motion = guardrails._measure_temporal_motion(str(source))
    assert motion is not None and motion["frames"] > 0
    assert not any("Temporal motion analysis unavailable" in issue.message for issue in report.issues)
    commands = [call.args[0] for call in run.call_args_list]
    assert {cmd[0] for cmd in commands} == set(configured_media.values())
    assert any("select='gt(scene,0.3)',showinfo" in cmd for cmd in commands)
    assert any("loudnorm=print_format=json" in cmd for cmd in commands)
    assert all(call.kwargs["timeout"] > 0 for call in run.call_args_list)


def test_invalid_probe_configuration_raises_custom_dependency_error(configured_media, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setenv("KINOCUT_FFPROBE_EXECUTABLE", str(tmp_path / "ffprobe"))
    with pytest.raises(FFprobeNotFoundError):
        DesignQualityGuardrails()._probe_video(str(source))


@pytest.mark.parametrize("method", ["_probe_video", "_detect_scene_changes"])
def test_guardrail_timeout_uses_custom_processing_error(configured_media, tmp_path, monkeypatch, method):
    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(
        ffmpeg_helpers.subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired("configured media tool", 600)),
    )
    with pytest.raises(ProcessingError, match="timed out"):
        getattr(DesignQualityGuardrails(), method)(str(source))


def test_motion_failure_remains_explicitly_unknown(configured_media, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(
        ffmpeg_helpers.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 1, "", "invalid media")),
    )
    assert DesignQualityGuardrails()._measure_temporal_motion(str(source)) is None


def test_invalid_probe_json_raises_custom_processing_error(configured_media, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.touch()
    monkeypatch.setattr(
        ffmpeg_helpers.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, "invalid JSON", "")),
    )
    with pytest.raises(ProcessingError, match="Invalid JSON from ffprobe"):
        DesignQualityGuardrails()._probe_video(str(source))


@pytest.mark.parametrize(
    "method", ["_probe_video", "_measure_temporal_motion", "_detect_scene_changes", "_calculate_audio_score"]
)
def test_guardrail_media_methods_validate_input_before_launch(tmp_path, monkeypatch, method):
    run = Mock()
    monkeypatch.setattr(ffmpeg_helpers.subprocess, "run", run)
    with pytest.raises(InputFileError):
        getattr(DesignQualityGuardrails(), method)(str(tmp_path / "missing.mp4"))
    run.assert_not_called()
