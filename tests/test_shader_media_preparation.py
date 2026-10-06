"""Native shader media controls; these do not certify GPU rendering."""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from kinocut import engine_glitch_shader as shader
from kinocut.errors import MCPVideoError, ProcessingError


def test_missing_renderer_is_typed(monkeypatch, sample_video, tmp_path):
    monkeypatch.setattr(shader, "_check_node", lambda: "node")
    monkeypatch.setattr(shader, "_RENDER_SCRIPT", tmp_path / "missing.mjs")
    with pytest.raises(MCPVideoError) as caught:
        shader.glitch_digital_feedback(str(sample_video), str(tmp_path / "out.mp4"))
    assert caught.value.code == "missing_shader_renderer"
    assert str(tmp_path) not in str(caught.value)


def test_dependencies_precede_media_work(monkeypatch, sample_video, tmp_path):
    monkeypatch.setattr(shader, "_check_node", lambda: "node")
    monkeypatch.setattr(shader, "_crush_sources_available", lambda: False)

    def forbidden(*args):
        pytest.fail("Media preparation ran before dependency validation")

    monkeypatch.setattr(shader, "_get_fps", forbidden)
    monkeypatch.setattr("kinocut.engine_probe.probe", forbidden)
    monkeypatch.setattr(shader, "_extract_frames", forbidden)
    with pytest.raises(MCPVideoError) as caught:
        shader.glitch_digital_feedback(str(sample_video), str(tmp_path / "out.mp4"))
    assert caught.value.code == "missing_crush_shaders"


def test_missing_source_audio_is_not_silently_dropped(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    _run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=s=16x16:r=10:d=0.1", str(frames / "frame_%06d.png")]
    )
    with pytest.raises(MCPVideoError):
        shader._assemble_video(str(frames), str(tmp_path / "missing.mp4"), str(tmp_path / "out.mp4"), "10/1")


def test_mux_failure_propagates(monkeypatch, tmp_path):
    error = ProcessingError("ffmpeg", 1, "mux failed")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(shader, "_run_command", fail)
    with pytest.raises(ProcessingError) as caught:
        shader._assemble_video("frames", "source.mp4", str(tmp_path / "out.mp4"), "10/1")
    assert caught.value is error


@pytest.mark.parametrize("probe", ["_get_video_fps", "_has_audio_stream"])
def test_upscale_probe_failure_propagates(monkeypatch, probe):
    from kinocut.ai_engine import upscale

    error = ProcessingError("ffprobe", 1, "probe failed")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(upscale, "_run_command", fail)
    with pytest.raises(ProcessingError) as caught:
        getattr(upscale, probe)("source.mp4")
    assert caught.value is error


@pytest.mark.parametrize("output", ["invalid", "video", "audio\ninvalid"])
def test_upscale_malformed_audio_probe_is_failure(monkeypatch, output):
    from kinocut.ai_engine import upscale

    monkeypatch.setattr(upscale, "_run_command", lambda *a, **k: SimpleNamespace(stdout=output))
    with pytest.raises(ProcessingError, match="Unexpected audio stream probe"):
        upscale._has_audio_stream("source.mp4")


@pytest.mark.parametrize("output", ["1/2/3", "nan", "inf", "0", "-1", "0/0", ""])
def test_invalid_upscale_rate_cannot_pass_resource_admission(monkeypatch, output):
    from kinocut.ai_engine import upscale

    monkeypatch.setattr(upscale, "_run_command", lambda *a, **k: SimpleNamespace(stdout=output))
    monkeypatch.setattr(upscale, "_get_video_duration", lambda _: 1)
    assert upscale._get_video_fps("source.mp4") is None
    with pytest.raises(MCPVideoError) as caught:
        upscale._estimate_frame_count("source.mp4")
    assert caught.value.code == "unknown_frame_rate"


def _run(args):
    return subprocess.run(args, check=True, capture_output=True, timeout=30).stdout


def test_frame_extraction_stops_at_overflow_sentinel(monkeypatch, tmp_path):
    source, frames = tmp_path / "source.mp4", tmp_path / "frames"
    frames.mkdir()
    _run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=s=16x16:r=10:d=0.5", "-c:v", "libx264", str(source)]
    )
    monkeypatch.setattr(shader, "MAX_SHADER_FRAMES", 2)
    assert shader._extract_frames(str(source), str(frames))["frame_count"] == 3
    with pytest.raises(MCPVideoError) as caught:
        shader._validate_shader_frame_count(3, str(source), max_frames=2)
    assert caught.value.code == "too_many_frames"


@pytest.mark.parametrize("operation", ["canvas", "render"])
@pytest.mark.parametrize("failure", ["timeout", "oserror"])
def test_node_failures_are_typed(monkeypatch, operation, failure):
    monkeypatch.setattr(shader.shutil, "which", lambda _: "node")

    def fail(*args, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] > 0
        if failure == "timeout":
            raise subprocess.TimeoutExpired("node", kwargs["timeout"])
        raise OSError("private renderer diagnostic")

    monkeypatch.setattr(shader.subprocess, "run", fail)
    with pytest.raises(ProcessingError) as caught:
        if operation == "canvas":
            shader._crush_canvas_available()
        else:
            shader._run_node_render("node", {})
    assert "private renderer diagnostic" not in str(caught.value)


def test_renderer_failure_keeps_code_and_bounds_stderr(monkeypatch):
    monkeypatch.setattr(shader.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="x" * 2000))
    with pytest.raises(MCPVideoError) as caught:
        shader._run_node_render("node", {})
    assert caught.value.code == "shader_render_failed"
    assert "x" * 501 not in str(caught.value)


@pytest.mark.parametrize("codec", ["aac", "libmp3lame", None])
@pytest.mark.parametrize("engine", ["shader", "realesrgan"])
def test_native_pipeline_preserves_audio(monkeypatch, codec, engine, tmp_path):
    source, output = tmp_path / "source.mp4", tmp_path / "output.mp4"
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=s=16x16:r=10:d=0.5"]
    if codec:
        command += ["-f", "lavfi", "-i", "sine=duration=0.5", "-c:a", codec]
    _run([*command, "-c:v", "libx264", str(source)])

    def copy_frames(node, params):
        for frame in Path(params["inputDir"]).glob("frame_*.png"):
            shutil.copyfile(frame, Path(params["outputDir"]) / frame.name)

    if engine == "shader":
        monkeypatch.setattr(shader, "_check_node", lambda: "node")
        monkeypatch.setattr(shader, "_check_shader_dependencies", lambda: None)
        monkeypatch.setattr(shader, "_run_node_render", copy_frames)
        result = shader.glitch_digital_feedback(str(source), str(output))
        assert result["frames_processed"] == 5
    else:
        pytest.importorskip("numpy")
        pytest.importorskip("PIL")
        from kinocut.ai_engine import upscale

        monkeypatch.setattr(
            upscale, "_init_realesrgan", lambda *a: SimpleNamespace(enhance=lambda image, **kw: (image, None))
        )
        upscale._upscale_with_realesrgan(source, output, "realesrgan", 2)

    def packets(path):
        data = _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_packets",
                "-show_data_hash",
                "sha256",
                "-show_entries",
                "packet=pts_time,dts_time,duration_time,data_hash,side_data_list",
                "-of",
                "json",
                str(path),
            ]
        )
        return json.loads(data).get("packets", [])

    assert packets(source) == packets(output)
    if codec:
        assert packets(output)

        def decode(path):
            return _run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "s16le", "-"])

        assert decode(source) == decode(output)
    else:
        assert packets(output) == []
