"""Attachment/ducking must reject empty sound and preserve prior outputs."""

import shutil
import struct
import subprocess
import json

import pytest

from kinocut.engine_audio_ops import add_audio, duck_audio
from kinocut.engine_audio_normalize import normalize_audio
from kinocut.engine_audio_mix import mix_audio
from kinocut.errors import MCPVideoError, ProcessingError

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")


def _ffmpeg(*args):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *map(str, args)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=60,
    )


@pytest.fixture
def sounds(tmp_path):
    video, silence, empty = tmp_path / "source.mp4", tmp_path / "silence.wav", tmp_path / "empty.wav"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=s=160x90:r=25:d=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:d=2",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "mpeg4",
        "-c:a",
        "aac",
        video,
    )
    _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "1", silence)
    empty.write_bytes(
        b"RIFF"
        + struct.pack("<I", 36)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 48000, 96000, 2, 16)
        + b"data"
        + struct.pack("<I", 0)
    )
    return video, silence, empty


@pytest.mark.parametrize("operation", [add_audio, duck_audio])
def test_empty_selected_audio_is_rejected_but_real_silence_is_accepted(sounds, tmp_path, operation):
    video, silence, empty = sounds
    output = tmp_path / "existing.mp4"
    output.write_bytes(video.read_bytes())
    before = output.read_bytes()
    with pytest.raises(MCPVideoError) as error:
        operation(str(video), str(empty), output_path=str(output))
    assert error.value.code == "invalid_media_duration"
    assert output.read_bytes() == before
    assert operation(str(video), str(silence), output_path=str(output)).success


@pytest.mark.parametrize("operation", [add_audio, duck_audio])
def test_added_media_without_audio_fails_before_replacing_destination(sounds, tmp_path, operation):
    video, _, _ = sounds
    picture, output = tmp_path / "missing-audio.mp4", tmp_path / "prior.mp4"
    _ffmpeg("-f", "lavfi", "-i", "color=s=160x90:r=25:d=1", "-c:v", "mpeg4", picture)
    output.write_bytes(video.read_bytes())
    before = output.read_bytes()
    with pytest.raises(MCPVideoError) as error:
        operation(str(video), str(picture), output_path=str(output))
    assert error.value.code == "missing_audio_stream"
    assert output.read_bytes() == before


@pytest.mark.parametrize(
    "operation,name",
    [
        (add_audio, "volume"),
        (add_audio, "fade_in"),
        (add_audio, "fade_out"),
        (add_audio, "start_time"),
        (duck_audio, "music_volume"),
        (duck_audio, "ratio"),
        (duck_audio, "threshold"),
        (duck_audio, "attack"),
        (duck_audio, "release"),
    ],
)
@pytest.mark.parametrize("value", [True, "bad", None, float("nan"), float("inf"), 10**1000])
def test_invalid_numbers_are_typed_before_render(sounds, tmp_path, operation, name, value):
    if name == "start_time" and value is None:
        pytest.skip("None intentionally means no delay")
    video, silence, _ = sounds
    with pytest.raises(MCPVideoError) as error:
        operation(str(video), str(silence), output_path=str(tmp_path / "out.mp4"), **{name: value})
    assert error.value.error_type == "validation_error"


@pytest.mark.parametrize("operation", [add_audio, duck_audio])
@pytest.mark.parametrize("phase", ["render", "decode", "receipt"])
def test_failure_after_output_started_preserves_destination(sounds, tmp_path, monkeypatch, operation, phase):
    from kinocut import engine_audio_ops as module

    video, silence, _ = sounds
    output = tmp_path / "prior.mp4"
    output.write_bytes(video.read_bytes())
    original = output.read_bytes()

    def fail(*args, **kwargs):
        if phase == "render":
            from pathlib import Path

            Path(args[0][-1]).write_bytes(b"partial encode")
        raise ProcessingError("injected failure", 1, "test failure")

    attribute = {"render": "_run_ffmpeg", "decode": "_validate_normalized_output", "receipt": "_build_edit_result"}[
        phase
    ]
    monkeypatch.setattr(module, attribute, fail, raising=False)
    with pytest.raises(ProcessingError):
        operation(str(video), str(silence), output_path=str(output))
    assert output.read_bytes() == original
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("operation", [normalize_audio, mix_audio, add_audio, duck_audio])
def test_corrupt_selected_aac_input_cannot_be_concealed_as_success(sounds, tmp_path, operation):
    video, _, _ = sounds
    damaged, output = tmp_path / "damaged.mp4", tmp_path / "prior.mp4"
    damaged.write_bytes(video.read_bytes())
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_packets",
            "-show_entries",
            "packet=pos,size",
            "-of",
            "json",
            str(damaged),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    packet = json.loads(process.stdout)["packets"][3]
    with damaged.open("r+b") as handle:
        handle.seek(int(packet["pos"]))
        handle.write(b"\xff" * int(packet["size"]))
    output.write_bytes(video.read_bytes())
    prior = output.read_bytes()
    with pytest.raises(MCPVideoError):
        if operation is normalize_audio:
            operation(str(damaged), output_path=str(output))
        elif operation is mix_audio:
            operation(str(video), [{"path": str(damaged)}], str(output))
        else:
            operation(str(video), str(damaged), output_path=str(output))
    assert output.read_bytes() == prior
    assert not list(tmp_path.glob(".kinocut_tmp_*"))
