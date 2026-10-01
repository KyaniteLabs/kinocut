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
    from kinocut.engine_audio_validation import _run_audio_ffmpeg
    from kinocut.ffmpeg_helpers import _run_ffmpeg

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
    # Prove the fixture against the same configured backend as the operation.
    # FFmpeg 6 can log a decoder error while returning zero, even with -xerror.
    decode = ["-v", "error", "-xerror", "-i", str(video), "-map", "0:a:0", "-vn", "-f", "null", "-"]
    assert _run_audio_ffmpeg(decode, runner=_run_ffmpeg).returncode == 0
    decode[decode.index("-i") + 1] = str(damaged)
    with pytest.raises(MCPVideoError):
        _run_audio_ffmpeg(decode, runner=_run_ffmpeg)
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


@pytest.mark.parametrize("level", ["error", "fatal", "panic"])
@pytest.mark.parametrize("color", [False, True])
def test_zero_exit_audio_process_still_rejects_logged_failures(level, color):
    from types import SimpleNamespace

    from kinocut.engine_audio_validation import _run_audio_ffmpeg

    def runner(command):
        assert command[:2] == ["-loglevel", "level+info"]
        text = f"[aac @ 0x1234] [{level}] decoder failed"
        if color:
            text = "\x1b[0;31m" + text + "\x1b[0m"
        return SimpleNamespace(returncode=0, stderr=text)

    with pytest.raises(ProcessingError) as error:
        _run_audio_ffmpeg(["-xerror", "-i", "fixture.mp4"], runner=runner)
    assert error.value.returncode == 0
    assert error.value.code == "ffmpeg_exit_0"


def test_audio_process_keeps_measurements_and_nonfatal_warnings():
    from types import SimpleNamespace

    from kinocut.engine_audio_validation import _run_audio_ffmpeg

    result = SimpleNamespace(
        returncode=0,
        stderr='[warning] [error] filename.mp4\n[info] [error] literal\n[info] {"input_i": -20, "name": "[error]"}\n',
    )
    calls = []
    assert _run_audio_ffmpeg(["-v", "error"], runner=lambda args: calls.append(args) or result) is result
    assert calls == [["-v", "level+error"]]


def test_audio_process_bounds_diagnostic_without_losing_zero_exit():
    from types import SimpleNamespace

    from kinocut.engine_audio_validation import _run_audio_ffmpeg
    from kinocut.limits import FFMPEG_STDERR_DIAGNOSTIC_BYTES

    stderr = "[info] progress\n" * 100_000
    stderr += "\r\x1b[31m[aac @ 0x123]\x1b[0m \x1b[31m[error]\x1b[0m " + "corrupt 音声" * 100_000
    result = SimpleNamespace(returncode=0, stderr=stderr)
    with pytest.raises(ProcessingError) as error:
        _run_audio_ffmpeg([], runner=lambda args: result)
    assert error.value.returncode == result.returncode
    assert error.value.full_stderr.startswith("\x1b[31m[aac @ 0x123]")
    assert len(error.value.full_stderr.encode("utf-8")) <= FFMPEG_STDERR_DIAGNOSTIC_BYTES
