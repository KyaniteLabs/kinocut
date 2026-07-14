"""Real-FFmpeg regressions for loss-proof ``add_audio`` duration policy (Plan 01 Task 1).

The historical "eaten outro" bug: replacing a 10s video's audio with a 3s clip
truncated the *output* to 3s (legacy ``-shortest``), silently discarding the
video's tail. The default ``keep_video`` policy must preserve the full video
duration; only the explicit ``shortest`` policy may shorten it, and it must warn.
Covers shorter / longer / equal audio, a silent source, and a multi-stream video.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from kinocut.engine_audio_ops import add_audio
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _get_video_duration

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def _make_video(path, duration: float, *, with_audio: bool = True) -> str:
    args = ["-f", "lavfi", "-i", f"color=c=blue:s=320x240:r=15:d={duration}"]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:d={duration}"]
    args += ["-shortest", "-pix_fmt", "yuv420p", str(path)]
    _ffmpeg(args)
    return str(path)


def _make_audio(path, duration: float) -> str:
    _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=44100:d={duration}", str(path)])
    return str(path)


def _make_multistream_video(path, duration: float) -> str:
    """A video carrying TWO audio streams (e.g. voice + music)."""
    _ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=green:s=320x240:r=15:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=330:sample_rate=44100:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=660:sample_rate=44100:d={duration}",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:a",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )
    return str(path)


def _audio_stream_count(path: str) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", path],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return len([line for line in out.splitlines() if line.strip()])


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("addaudio")
    return {
        "video_10s": _make_video(d / "v10.mp4", 10.0),
        "video_10s_silent": _make_video(d / "v10s.mp4", 10.0, with_audio=False),
        "video_multistream": _make_multistream_video(d / "vmulti.mp4", 10.0),
        "audio_3s": _make_audio(d / "a3.wav", 3.0),
        "audio_10s": _make_audio(d / "a10.wav", 10.0),
        "audio_15s": _make_audio(d / "a15.wav", 15.0),
    }


def test_keep_video_default_preserves_outro(tmp_path, media):
    out = tmp_path / "out.mp4"
    add_audio(media["video_10s"], media["audio_3s"], output_path=str(out))  # no policy => default
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.2  # outro NOT eaten


def test_shortest_policy_warns_and_shortens(tmp_path, media):
    out = tmp_path / "s.mp4"
    res = add_audio(media["video_10s"], media["audio_3s"], duration_policy="shortest", output_path=str(out))
    assert _get_video_duration(str(out)) < 4.0
    assert any("duration" in w.lower() for w in res.warnings)


@pytest.mark.parametrize("audio_key", ["audio_3s", "audio_10s", "audio_15s"])
def test_keep_video_holds_video_duration_for_any_audio_length(tmp_path, media, audio_key):
    out = tmp_path / f"kv_{audio_key}.mp4"
    add_audio(media["video_10s"], media[audio_key], duration_policy="keep_video", output_path=str(out))
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3


def test_pad_audio_fills_short_audio_to_video(tmp_path, media):
    out = tmp_path / "pad.mp4"
    add_audio(media["video_10s"], media["audio_3s"], duration_policy="pad_audio", output_path=str(out))
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3


def test_loop_audio_fills_short_audio_to_video(tmp_path, media):
    out = tmp_path / "loop.mp4"
    add_audio(media["video_10s"], media["audio_3s"], duration_policy="loop_audio", output_path=str(out))
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3


def test_trim_audio_caps_long_audio_to_video(tmp_path, media):
    out = tmp_path / "trim.mp4"
    add_audio(media["video_10s"], media["audio_15s"], duration_policy="trim_audio", output_path=str(out))
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3


def test_silent_source_video_keeps_full_duration(tmp_path, media):
    out = tmp_path / "silent.mp4"
    add_audio(media["video_10s_silent"], media["audio_3s"], output_path=str(out))
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3


def test_mix_mode_preserves_video_duration_by_default(tmp_path, media):
    out = tmp_path / "mix.mp4"
    add_audio(media["video_10s"], media["audio_3s"], mix=True, output_path=str(out))
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3


def test_invalid_duration_policy_is_rejected(tmp_path, media):
    with pytest.raises(MCPVideoError):
        add_audio(media["video_10s"], media["audio_3s"], duration_policy="bogus", output_path=str(tmp_path / "x.mp4"))


def test_mix_keep_video_caps_longer_added_audio(tmp_path, media):
    out = tmp_path / "mixlong.mp4"
    add_audio(media["video_10s"], media["audio_15s"], mix=True, output_path=str(out))
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3  # not stretched to 15s


def test_mix_shortest_actually_shortens(tmp_path, media):
    out = tmp_path / "mixshort.mp4"
    res = add_audio(media["video_10s"], media["audio_3s"], mix=True, duration_policy="shortest", output_path=str(out))
    assert _get_video_duration(str(out)) < 4.0  # genuinely shortened, not held at 10s
    assert any("duration" in w.lower() for w in res.warnings)


@pytest.mark.parametrize("policy", ["loop_audio", "pad_audio"])
def test_mix_loop_or_pad_fails_closed(tmp_path, media, policy):
    with pytest.raises(MCPVideoError):
        add_audio(
            media["video_10s"], media["audio_3s"], mix=True, duration_policy=policy, output_path=str(tmp_path / "x.mp4")
        )


def test_invalid_policy_error_does_not_echo_raw_text(tmp_path, media):
    hostile = "../../etc/passwd <script>"
    with pytest.raises(MCPVideoError) as excinfo:
        add_audio(media["video_10s"], media["audio_3s"], duration_policy=hostile, output_path=str(tmp_path / "x.mp4"))
    assert hostile not in str(excinfo.value)  # raw invalid input never echoed


def test_start_time_replace_keep_video_preserves_outro(tmp_path, media):
    out = tmp_path / "st_replace.mp4"
    res = add_audio(
        media["video_10s"], media["audio_3s"], start_time=1.0, duration_policy="keep_video", output_path=str(out)
    )
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3  # delayed audio, outro kept
    assert _audio_stream_count(res.output_path) == 1


def test_start_time_mix_keep_video_caps_at_video(tmp_path, media):
    out = tmp_path / "st_mix.mp4"
    add_audio(
        media["video_10s"],
        media["audio_15s"],
        mix=True,
        start_time=1.0,
        duration_policy="keep_video",
        output_path=str(out),
    )
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3  # delayed + longer audio, still capped


def test_multistream_source_video_probe_has_two_audio(media):
    assert _audio_stream_count(media["video_multistream"]) == 2


@pytest.mark.parametrize("policy", ["keep_video", "trim_audio", "pad_audio", "loop_audio"])
def test_multistream_source_replace_keeps_video_duration(tmp_path, media, policy):
    out = tmp_path / f"multi_{policy}.mp4"
    res = add_audio(media["video_multistream"], media["audio_3s"], duration_policy=policy, output_path=str(out))
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3
    assert _audio_stream_count(res.output_path) == 1  # replaced to a single mapped track


def test_multistream_source_mix_keep_video_caps(tmp_path, media):
    out = tmp_path / "multi_mix.mp4"
    add_audio(
        media["video_multistream"], media["audio_15s"], mix=True, duration_policy="keep_video", output_path=str(out)
    )
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3


@pytest.mark.parametrize("policy", ["loop_audio", "pad_audio"])
def test_multistream_mix_loop_or_pad_fails_closed(tmp_path, media, policy):
    with pytest.raises(MCPVideoError):
        add_audio(
            media["video_multistream"],
            media["audio_3s"],
            mix=True,
            duration_policy=policy,
            output_path=str(tmp_path / "x.mp4"),
        )


def test_add_audio_remains_backward_compatible(tmp_path, media):
    # The pre-existing positional signature still works (new kwarg is additive).
    out = tmp_path / "compat.mp4"
    res = add_audio(media["video_10s"], media["audio_3s"], 1.0, 0.0, 0.0, False, None, str(out))
    assert res.output_path.endswith("compat.mp4")
    assert abs(_get_video_duration(str(out)) - 10.0) < 0.3
