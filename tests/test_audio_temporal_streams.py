"""Real temporal and stream-selection controls for normalization and mixing."""

import re
import json
import shutil
import subprocess

import pytest

from kinocut.engine_audio_mix import mix_audio
from kinocut.engine_audio_normalize import normalize_audio
from kinocut.engine_audio_ops import add_audio
from kinocut.ffmpeg_helpers import _run_ffprobe_json

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs FFmpeg")


def _ffmpeg(*args):
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-y", *map(str, args)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )


def _rms(path, start, duration=0.15, filters=""):
    # Fill a delayed stream's leading timeline gap so it measures as silence.
    chain = f"aresample=48000:async=1:first_pts=0,atrim=start={start}:duration={duration},"
    process = _ffmpeg(
        "-i", path, "-map", "0:a:0", "-vn", "-af", chain + filters + "astats=measure_perchannel=none", "-f", "null", "-"
    )
    value = re.search(r"RMS level dB: (-inf|-?[\d.]+)", process.stderr).group(1)
    return -200 if value == "-inf" else float(value)


def _audio(path):
    return next(stream for stream in _run_ffprobe_json(str(path))["streams"] if stream["codec_type"] == "audio")


def _picture_pts(path):
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "csv=p=0",
            str(path),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return [float(line.split(",")[0]) for line in process.stdout.splitlines() if line.strip()]


def _picture_presentation_end(path):
    """Independent fixture oracle: muxer versions can change the final packet width."""
    process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_packets",
            "-show_entries",
            "packet=pts_time,duration_time",
            "-of",
            "json",
            str(path),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    packets = json.loads(process.stdout)["packets"]
    assert len(packets) == 4
    assert all(float(packet["duration_time"]) > 0 for packet in packets)
    return max(float(packet["pts_time"]) + float(packet["duration_time"]) for packet in packets)


@pytest.mark.parametrize("suffix", ["mp4", "wav"])
def test_normalization_fades_follow_late_audio_and_keep_full_audible_tail(tmp_path, suffix):
    source, output = tmp_path / "late.mp4", tmp_path / f"normalized.{suffix}"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=s=160x90:r=25:d=3",
        "-itsoffset",
        "1",
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
        "-fps_mode",
        "passthrough",
        "-c:a",
        "aac",
        source,
    )
    # MPEG4 muxing may expose one AAC priming packet before the requested offset.
    assert float(_audio(source)["start_time"]) == pytest.approx(1, abs=0.03)
    result = normalize_audio(str(source), output_path=str(output))
    first, tail = (1.3, 2.3) if suffix == "mp4" else (0.3, 1.3)
    assert _rms(result.output_path, tail) > -30
    assert _rms(result.output_path, first) == pytest.approx(_rms(result.output_path, tail), abs=1)
    if suffix == "mp4":
        assert _rms(result.output_path, 0.3) < -80
        assert _picture_pts(source) == _picture_pts(output)
    else:
        assert float(_audio(output)["duration"]) == pytest.approx(float(_audio(source)["duration"]), abs=0.001)


@pytest.mark.parametrize("suffix", ["mp4", "wav"])
def test_normalization_uses_primary_audio_even_when_later_stream_is_default(tmp_path, suffix):
    source, output = tmp_path / "multiple.mp4", tmp_path / f"normalized.{suffix}"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=s=160x90:r=25:d=5",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=32000:d=2",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1800:sample_rate=48000:d=5",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map",
        "2:a:0",
        "-ac:a:1",
        "2",
        "-disposition:a:0",
        "0",
        "-disposition:a:1",
        "default",
        "-c:v",
        "mpeg4",
        "-c:a",
        "aac",
        source,
    )
    streams = [stream for stream in _run_ffprobe_json(str(source))["streams"] if stream["codec_type"] == "audio"]
    assert streams[0]["disposition"]["default"] == 0 and streams[1]["disposition"]["default"] == 1
    result = normalize_audio(str(source), output_path=str(output))
    selected = _audio(output)
    assert selected["channels"] == 1 and selected["sample_rate"] == "32000"
    assert float(selected["duration"]) == pytest.approx(2, abs=0.04)
    # Content must also be the 440Hz primary stream, not merely resampled secondary audio.
    assert _rms(output, 0.5, filters="lowpass=f=700,") > _rms(output, 0.5, filters="highpass=f=700,") + 6
    assert result.audio_codec == ("aac" if suffix == "mp4" else "pcm_s16le")


@pytest.mark.parametrize("suffix", ["mp4", "mkv"])
def test_vfr_picture_presentation_extent_controls_audio_not_stream_duration(tmp_path, suffix):
    source, added, output = tmp_path / f"vfr.{suffix}", tmp_path / "added.wav", tmp_path / "mixed.mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=s=160x90:r=25:d=2.04",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:d=5",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        r"select=eq(n\,0)+eq(n\,5)+eq(n\,25)+eq(n\,50)",
        "-fps_mode",
        "vfr",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        source,
    )
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:d=3", added)
    assert _picture_pts(source) == pytest.approx([0, 0.2, 1, 2], abs=0.001)
    picture_end = _picture_presentation_end(source)
    # The final encoded packet is 40ms with some muxers and 800ms with others.
    # Preserve the actual presentation interval, not the nominal lavfi input
    # length or stream.duration (which is unreliable with reordered VFR packets).
    result = mix_audio(str(source), [{"path": str(added)}], str(output), keep_source=False)
    assert result.duration == pytest.approx(picture_end, abs=0.04)
    assert float(_audio(output)["duration"]) == pytest.approx(picture_end, abs=0.04)
    assert _rms(output, 1.7) > -30
    assert _rms(output, picture_end - 0.15, duration=0.1) > -30
    assert _picture_pts(output) == _picture_pts(source)


@pytest.mark.parametrize("suffix", ["mp4", "mkv"])
def test_added_video_track_fades_its_audio_extent_not_longer_picture(tmp_path, suffix):
    source, track = tmp_path / "base.mp4", tmp_path / f"track.{suffix}"
    _ffmpeg("-f", "lavfi", "-i", "color=s=160x90:r=25:d=4", "-c:v", "mpeg4", source)
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=s=160x90:r=25:d=4",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:sample_rate=48000:d=1",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "mpeg4",
        "-c:a",
        "aac",
        track,
    )
    plain = mix_audio(str(source), [{"path": str(track)}], str(tmp_path / "plain.mp4"), keep_source=False)
    faded = mix_audio(
        str(source), [{"path": str(track), "fade_out": 1}], str(tmp_path / "faded.mp4"), keep_source=False
    )
    assert _rms(faded.output_path, 0.8) < _rms(plain.output_path, 0.8) - 12
    assert faded.duration == pytest.approx(4, abs=0.04)


@pytest.mark.parametrize("codec,rate,channels", [("pcm_u8", 8000, 1), ("pcm_s24le", 32000, 2), ("pcm_f32le", 48000, 6)])
def test_integer_float_and_surround_sources_normalize_and_mix_without_losing_layout(tmp_path, codec, rate, channels):
    source, picture = tmp_path / "sound.wav", tmp_path / "picture.mp4"
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={rate}:d=2", "-ac", channels, "-c:a", codec, source)
    _ffmpeg("-f", "lavfi", "-i", "color=s=160x90:r=25:d=2", "-c:v", "mpeg4", picture)
    normalized = normalize_audio(str(source), output_path=str(tmp_path / "normalized.wav"))
    audio = _audio(normalized.output_path)
    assert audio["sample_rate"] == str(rate) and audio["channels"] == channels
    assert float(audio["duration"]) == pytest.approx(2, abs=0.01)
    assert _rms(normalized.output_path, 0.5) > -35
    mixed = mix_audio(str(picture), [{"path": str(source)}], str(tmp_path / "mixed.mp4"), keep_source=False)
    assert _audio(mixed.output_path)["channels"] == 2
    assert _audio(mixed.output_path)["sample_rate"] == "48000"
    assert mixed.duration == pytest.approx(2, abs=0.04)
    assert _rms(mixed.output_path, 0.5) > -40


@pytest.mark.parametrize("mix", [False, True])
@pytest.mark.parametrize("scenario", ["delay", "native_delay", "loop"])
def test_attachment_fades_follow_audible_sound_and_final_loop_window(tmp_path, mix, scenario):
    picture, sound = tmp_path / "picture.mp4", tmp_path / "sound.wav"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=s=160x90:r=25:d=3",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-t",
        "3",
        "-c:v",
        "mpeg4",
        "-c:a",
        "aac",
        picture,
    )
    delay, origin = 0.8, 0.8
    if scenario == "native_delay":
        sound, delay, origin = tmp_path / "late-sound.mp4", None, 0.5
        _ffmpeg(
            "-f",
            "lavfi",
            "-i",
            "color=s=160x90:r=25:d=3",
            "-itsoffset",
            "0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=1",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            sound,
        )
    else:
        length = 0.5 if scenario == "loop" else 1
        _ffmpeg("-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:d={length}", sound)
    policy = "loop_audio" if scenario == "loop" else "keep_video"
    common = {"mix": mix, "start_time": delay, "duration_policy": policy}
    plain = add_audio(str(picture), str(sound), output_path=str(tmp_path / "plain.mp4"), **common)
    faded = add_audio(
        str(picture), str(sound), fade_in=0.4, fade_out=0.4, output_path=str(tmp_path / "faded.mp4"), **common
    )
    assert (
        _rms(faded.output_path, origin + 0.04, duration=0.08)
        < _rms(plain.output_path, origin + 0.04, duration=0.08) - 7
    )
    tail = 2.88 if scenario == "loop" else origin + 0.88
    assert _rms(faded.output_path, tail, duration=0.06) < _rms(plain.output_path, tail, duration=0.06) - 9
    assert _rms(faded.output_path, origin + 0.02, duration=0.04) > -70, "fade starts at sound; it does not erase it"
    assert faded.duration == pytest.approx(3, abs=0.04)
