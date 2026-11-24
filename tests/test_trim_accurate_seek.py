"""accurate=True trims seek the input: the same frames as output seeking, without decoding the file up to start."""

from __future__ import annotations

import shutil
import subprocess
import asyncio
import json
import sys

import pytest

from kinocut import Client
from kinocut.engine_edit import trim
from kinocut.engine_timeline import edit_timeline
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _build_ffmpeg_cmd
from kinocut.server_tools_basic import video_trim

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _ffmpeg(*args: str) -> str:
    done = subprocess.run(["ffmpeg", "-hide_banner", "-y", *args], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout


def _frames(path: str) -> list[str]:
    return [
        line.rsplit(",", 1)[-1].strip()
        for line in _ffmpeg("-i", path, "-an", "-f", "framemd5", "-").splitlines()
        if line and not line.startswith("#")
    ]


@pytest.fixture(scope="module")
def numbered(tmp_path_factory):
    # Each frame shows its own number; a keyframe every 2 s, so 5.5 s falls between two of them.
    video = tmp_path_factory.mktemp("trim") / "numbered-«redacted-sk-path».mp4"
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=320x240:rate=30:duration=10",
        "-c:v",
        "libx264",
        "-g",
        "60",
        "-pix_fmt",
        "yuv420p",
        str(video),
    )
    return str(video)


@pytest.mark.parametrize("start", [5.5, 2.0, 0.4])
def test_accurate_trim_gives_the_frames_output_seeking_gives(numbered, tmp_path, start):
    reference = str(tmp_path / "reference.mp4")
    _ffmpeg("-i", numbered, "-ss", str(start), "-t", "1.5", *_build_ffmpeg_cmd(output_path=reference))
    fast = str(tmp_path / "fast.mp4")
    trim(numbered, start=start, duration=1.5, output_path=fast, accurate=True)
    assert _frames(fast) == _frames(reference)


@pytest.fixture(scope="module")
def non_keyframe_reference(numbered, tmp_path_factory):
    reference = str(tmp_path_factory.mktemp("trim-reference") / "reference.mp4")
    _ffmpeg("-i", numbered, "-ss", "5.5", "-t", "1.5", *_build_ffmpeg_cmd(output_path=reference))
    return _frames(reference)


@pytest.mark.parametrize(
    "surface, accurate",
    [(surface, accurate) for surface in ("python", "mcp", "client") for accurate in (None, False, True)]
    + [("cli", None), ("cli", True)],
)
def test_legacy_trim_surfaces_keep_the_same_frames(
    surface, accurate, numbered, non_keyframe_reference, tmp_path, monkeypatch, capsys
):
    output = str(tmp_path / "output.mp4")
    kwargs = {} if accurate is None else {"accurate": accurate}
    if surface == "mcp":
        payload = asyncio.run(video_trim(numbered, start=5.5, duration=1.5, output_path=output, review=False, **kwargs))
        assert payload["success"] and payload["output_path"] == output, payload
    elif surface == "cli":
        from kinocut.__main__ import main

        arguments = ["kino", "--format", "json", "trim", numbered, "-s", "5.5", "-d", "1.5", "-o", output]
        monkeypatch.setattr(sys, "argv", arguments + (["--accurate"] if accurate else []))
        main()
        assert json.loads(capsys.readouterr().out)["output_path"] == output
    elif surface == "client":
        assert Client().trim(numbered, start=5.5, duration=1.5, output=output, **kwargs).output_path == output
    elif accurate is None:
        assert trim(numbered, 5.5, 1.5, output_path=output).output_path == output
    else:
        assert trim(numbered, start=5.5, duration=1.5, output_path=output, **kwargs).output_path == output
    assert _frames(output) == non_keyframe_reference


@pytest.mark.parametrize("absolute_end", [False, True])
def test_timeline_honors_non_keyframe_start_and_absolute_end_precedence(numbered, tmp_path, absolute_end):
    clip = {"source": numbered, "trim_start": 5.5, "duration": 0.5 if absolute_end else 1.5}
    if absolute_end:
        clip["trim_end"] = 7.0
    cut = str(tmp_path / "cut.mp4")
    _ffmpeg("-i", numbered, "-ss", "5.5", "-t", "1.5", *_build_ffmpeg_cmd(output_path=cut))
    reference = edit_timeline({"tracks": [{"type": "video", "clips": [{"source": cut}]}]}, str(tmp_path / "ref.mp4"))
    actual = edit_timeline({"tracks": [{"type": "video", "clips": [clip]}]}, str(tmp_path / "out.mp4"))
    assert len(_frames(actual.output_path)) == 45
    assert _frames(actual.output_path) == _frames(reference.output_path)


def test_stream_copy_preserves_source_frames_and_warns_about_keyframe_snap(numbered, tmp_path):
    output = str(tmp_path / "copy-«redacted-sk-path».mkv")
    result = trim(numbered, 5.5, 1.5, output_path=output, stream_copy=True)
    original_frames = set(_frames(numbered))
    copied_frames = _frames(output)
    assert copied_frames and set(copied_frames) <= original_frames
    assert result.output_path == output
    assert len(result.warnings) == 1 and "keyframe" in result.warnings[0].lower()
    assert len(result.warnings[0]) < 180 and "«redacted-sk-path»" not in result.warnings[0]


def test_stream_copy_refuses_incompatible_container_without_publishing(numbered, tmp_path):
    output = tmp_path / "copy-«redacted-sk-path».webm"
    with pytest.raises(MCPVideoError) as exc:
        trim(numbered, 5.5, 1.5, output_path=str(output), stream_copy=True)
    assert exc.value.code == "trim_stream_copy_failed"
    assert "stream_copy=False" in str(exc.value)
    assert "«redacted-sk-path»" not in json.dumps(exc.value.to_dict(), ensure_ascii=False)
    assert not output.exists()


def test_stream_copy_preserves_multiple_audio_tracks(numbered, tmp_path):
    from kinocut.ffmpeg_helpers import _run_ffprobe_json

    dual = str(tmp_path / "dual_audio.mp4")
    _ffmpeg(
        "-i",
        numbered,
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=8",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:duration=8",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-map",
        "2:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        dual,
    )
    output = str(tmp_path / "dual_copy.mp4")
    result = trim(dual, 1.0, 2.0, output_path=output, stream_copy=True)
    assert result.output_path == output
    probed = _run_ffprobe_json(output)
    audio_streams = [s for s in probed.get("streams", []) if s.get("codec_type") == "audio"]
    assert len(audio_streams) == 2
