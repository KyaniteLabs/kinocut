"""Native frame extraction enforces the AI budget before model inference."""

from __future__ import annotations

import builtins
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from kinocut.ai_engine import upscale
from kinocut.errors import MCPVideoError, ProcessingError


@pytest.fixture
def clip_factory(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is required for native frame admission controls")

    def create(count, *, audio=False):
        path = tmp_path / f"frames-{count}-audio-{audio}.mp4"
        command = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=32x32:r=5"]
        if audio:
            command.extend(["-f", "lavfi", "-i", f"sine=frequency=440:duration={count / 5}"])
        command.extend(["-frames:v", str(count), "-c:v", "libx264"])
        if audio:
            command.extend(["-c:a", "aac", "-shortest"])
        command.append(str(path))
        subprocess.run(
            command,
            check=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            capture_output=True,
        )
        return path

    return create


def test_extractor_stops_at_overflow_sentinel_and_rejects(clip_factory, tmp_path, monkeypatch):
    clip = clip_factory(5)
    frames = tmp_path / "frames"
    frames.mkdir()
    monkeypatch.setattr(upscale, "MAX_AI_UPSCALE_FRAMES", 2)
    with pytest.raises(MCPVideoError) as failure:
        upscale._extract_frames(str(clip), frames)
    assert failure.value.error_type == "resource_error"
    assert failure.value.code == "frame_count_too_large"
    assert len(list(frames.glob("frame_*.png"))) == 3


@pytest.mark.parametrize("count", [1, 2])
def test_at_or_below_budget_preserves_all_frames(clip_factory, tmp_path, monkeypatch, count):
    clip = clip_factory(count)
    frames = tmp_path / "frames"
    frames.mkdir()
    monkeypatch.setattr(upscale, "MAX_AI_UPSCALE_FRAMES", 2)
    extracted = upscale._extract_frames(str(clip), frames)
    assert len(extracted) == count
    assert extracted == sorted(frames.glob("frame_*.png"))


def test_underestimated_preflight_cannot_reach_realesrgan_inference(clip_factory, tmp_path, monkeypatch):
    clip = clip_factory(5)
    monkeypatch.setattr(upscale, "MAX_AI_UPSCALE_FRAMES", 2)
    monkeypatch.setattr(upscale, "_estimate_frame_count", lambda path: 1)
    monkeypatch.setattr(upscale, "_init_realesrgan", lambda *a: pytest.fail("overflow reached model initialization"))
    upscale._validate_upscale_resource_limits(str(clip))
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"prior output")
    with pytest.raises(MCPVideoError) as failure:
        upscale._upscale_with_realesrgan(clip, output, "realesrgan", 2)
    assert failure.value.code == "frame_count_too_large"
    assert output.read_bytes() == b"prior output"


def test_no_frames_retains_processing_error(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(upscale, "_run_command", lambda cmd, **kwargs: commands.append(cmd))
    with pytest.raises(ProcessingError, match="No frames extracted"):
        upscale._extract_frames("empty.mp4", tmp_path)
    assert len(commands) == 1
    assert commands[0][commands[0].index("-frames:v") + 1] == str(upscale.MAX_AI_UPSCALE_FRAMES + 1)


def _select_backend(monkeypatch, backend):
    original_import = builtins.__import__

    def select(name, *args, **kwargs):
        if name.startswith(("realesrgan", "basicsr")):
            if backend == "opencv":
                raise ImportError("test selects existing fallback")
            return object()  # Only the availability imports execute; no model code.
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", select)


@pytest.mark.parametrize("backend", ["opencv", "realesrgan"])
def test_failed_reconstruction_preserves_prior_output_and_source(clip_factory, tmp_path, monkeypatch, backend):
    clip = clip_factory(2)
    original_source = clip.read_bytes()
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"prior output")
    _select_backend(monkeypatch, backend)
    destinations = []

    def fail(source, destination, *args):
        destinations.append(str(destination))
        assert str(destination) != str(output)
        upscale._validate_output_path(str(destination))
        destination = type(clip)(destination)
        destination.write_bytes(b"partial reconstruction")
        raise ProcessingError("ffmpeg", 1, "simulated reconstruction failure")

    function = "_ai_upscale_opencv" if backend == "opencv" else "_upscale_with_realesrgan"
    monkeypatch.setattr(upscale, function, fail)
    with pytest.raises(ProcessingError):
        upscale.ai_upscale(str(clip), str(output))
    assert output.read_bytes() == b"prior output"
    assert clip.read_bytes() == original_source
    assert len(destinations) == 1
    assert not type(clip)(destinations[0]).exists()


@pytest.mark.parametrize("backend", ["opencv", "realesrgan"])
def test_success_publishes_valid_native_media_and_returns_requested_path(clip_factory, tmp_path, monkeypatch, backend):
    clip = clip_factory(2)
    source_bytes = clip.read_bytes()
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"prior output")
    _select_backend(monkeypatch, backend)
    calls = []

    def reconstruct(source, destination, *args):
        calls.append((str(source), str(destination), args))
        assert str(destination) != str(output)
        shutil.copyfile(source, destination)
        return str(destination)

    function = "_ai_upscale_opencv" if backend == "opencv" else "_upscale_with_realesrgan"
    monkeypatch.setattr(upscale, function, reconstruct)
    assert upscale.ai_upscale(str(clip), str(output), scale=4, model="bsrgan") == str(output)
    assert output.read_bytes() == source_bytes
    assert clip.read_bytes() == source_bytes
    assert calls[0][0] == str(clip)
    assert calls[0][2] == ((4,) if backend == "opencv" else ("bsrgan", 4))


@pytest.mark.parametrize("mux_fails", [False, True], ids=["audio-preserved", "audio-mux-fails"])
def test_realesrgan_audio_mux_failure_cannot_publish_silent_success(clip_factory, tmp_path, monkeypatch, mux_fails):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL")
    clip = clip_factory(2, audio=True)
    source_bytes = clip.read_bytes()
    assert upscale._has_audio_stream(str(clip))
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"prior output")
    _select_backend(monkeypatch, "realesrgan")
    monkeypatch.setattr(
        upscale, "_init_realesrgan", lambda *a: SimpleNamespace(enhance=lambda image, **kw: (image, None))
    )
    if mux_fails:

        def fail_mux(*args, **kwargs):
            assert kwargs["audio_source"] == str(clip)
            raise ProcessingError("ffmpeg", 1, "audio mux failed")

        monkeypatch.setattr(upscale, "_reconstruct_video", fail_mux)
        with pytest.raises(ProcessingError, match="audio mux failed"):
            upscale.ai_upscale(str(clip), str(output))
        assert output.read_bytes() == b"prior output"
    else:
        assert upscale.ai_upscale(str(clip), str(output)) == str(output)
        assert upscale._has_audio_stream(str(output))
    assert clip.read_bytes() == source_bytes


@pytest.mark.parametrize("alias", ["same-path", "hardlink"])
def test_source_output_alias_is_rejected_before_backend(clip_factory, tmp_path, monkeypatch, alias):
    clip = clip_factory(2)
    source_bytes = clip.read_bytes()
    output = clip
    if alias == "hardlink":
        output = tmp_path / "alias.mp4"
        os.link(clip, output)
    monkeypatch.setattr(upscale, "_ai_upscale_opencv", lambda *a: pytest.fail("alias reached backend"))
    monkeypatch.setattr(upscale, "_upscale_with_realesrgan", lambda *a: pytest.fail("alias reached backend"))
    with pytest.raises(MCPVideoError) as failure:
        upscale.ai_upscale(str(clip), str(output))
    assert failure.value.error_type == "validation_error"
    assert failure.value.code == "invalid_output_path"
    assert clip.read_bytes() == source_bytes


def test_opencv_overflow_rejects_before_model_download_or_init(clip_factory, tmp_path, monkeypatch):
    clip = clip_factory(5)
    monkeypatch.setattr(upscale, "MAX_AI_UPSCALE_FRAMES", 2)
    monkeypatch.setattr(upscale, "_download_fsrcnn_model", lambda *a: pytest.fail("overflow downloaded model"))
    monkeypatch.setattr(upscale, "_init_opencv_sr", lambda *a: pytest.fail("overflow initialized model"))
    with pytest.raises(MCPVideoError) as failure:
        upscale._ai_upscale_opencv(str(clip), str(tmp_path / "output.mp4"), 2)
    assert failure.value.code == "frame_count_too_large"


@pytest.mark.parametrize("fail_at", [None, 2], ids=["all-writes-succeed", "write-fails-after-first"])
def test_opencv_frame_write_result_controls_publication(clip_factory, tmp_path, monkeypatch, fail_at):
    clip = clip_factory(4)
    source_bytes = clip.read_bytes()
    output = tmp_path / "existing.mp4"
    output.write_bytes(b"prior output")
    _select_backend(monkeypatch, "opencv")
    writes = []

    def imwrite(destination, frame):
        writes.append(destination)
        if fail_at == len(writes):
            return False
        shutil.copyfile(frame, destination)
        return True

    fake_cv2 = SimpleNamespace(imread=lambda path: path, imwrite=imwrite)
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setattr(upscale, "_download_fsrcnn_model", lambda scale: tmp_path / "unused-model.pb")
    monkeypatch.setattr(upscale, "_init_opencv_sr", lambda *a: SimpleNamespace(upsample=lambda frame: frame))
    reconstructed = []
    real_reconstruct = upscale._reconstruct_video

    def reconstruct(*args, **kwargs):
        reconstructed.append(args)
        return real_reconstruct(*args, **kwargs)

    monkeypatch.setattr(upscale, "_reconstruct_video", reconstruct)
    if fail_at is not None:
        with pytest.raises(ProcessingError, match="Failed to save upscaled frame"):
            upscale.ai_upscale(str(clip), str(output))
        assert len(writes) == 2
        assert reconstructed == []
        assert output.read_bytes() == b"prior output"
    else:
        assert upscale.ai_upscale(str(clip), str(output)) == str(output)
        assert len(writes) == 4
        assert len(reconstructed) == 1
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_frames",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(output),
            ],
            timeout=30,
            check=True,
            capture_output=True,
            text=True,
        )
        assert probe.stdout.strip() == "4"
    assert clip.read_bytes() == source_bytes
