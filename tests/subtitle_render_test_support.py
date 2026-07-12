"""Shared fixtures and media helpers for subtitle render tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
requires_ffmpeg = pytest.mark.skipif(not (_FFMPEG and _FFPROBE), reason="ffmpeg/ffprobe not installed")

# width, height per aspect family — even dimensions for h264.
_ASPECTS = {"vertical": (216, 384), "horizontal": (384, 216), "square": (256, 256)}

# Authored ASS: PlayRes 1080x1920 and a centered \pos — burning must preserve
# both the resolution reference and the explicit position.
_AUTHORED_ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,120,&H00FFFFFF,&H00000000,&H80000000,0,0,5,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,{\\pos(540,960)}AUTHORED
"""


def _subtitles_common():
    from kinocut import subtitles_common

    return subtitles_common


def _ffprobe_json(path: str) -> dict:
    from kinocut.ffmpeg_helpers import _run_ffprobe_json

    return _run_ffprobe_json(path)


def _video_stream(data: dict) -> dict:
    return next(s for s in data.get("streams", []) if s.get("codec_type") == "video")


def _has_audio(data: dict) -> bool:
    return any(s.get("codec_type") == "audio" for s in data.get("streams", []))


def _make_testsrc_video(path: Path, width: int, height: int, seconds: int = 3) -> str:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:duration={seconds}:rate=15",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        timeout=60,
    )
    if not path.is_file():
        pytest.skip("could not generate fixture video")
    return str(path)


def _make_solid_video(path: Path, width: int, height: int, seconds: int = 2) -> str:
    """Solid-black video with an audio track (for pixel proofs + A/V preservation)."""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:d={seconds}:r=15",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        timeout=60,
    )
    if not path.is_file():
        pytest.skip("could not generate fixture video")
    return str(path)


def _extract_ppm(video_path: str, ts: float) -> tuple[int, int, bytes]:
    """Decode a single frame at ``ts`` seconds to a raw (w, h, rgb_bytes) triple."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            str(ts),
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "ppm",
            "-",
        ],
        capture_output=True,
        timeout=60,
    )
    data = proc.stdout
    if not data.startswith(b"P6"):
        pytest.skip("could not extract ppm frame")
    idx = 2
    header: list[int] = []
    while len(header) < 3:
        while idx < len(data) and data[idx : idx + 1].isspace():
            idx += 1
        start = idx
        while idx < len(data) and not data[idx : idx + 1].isspace():
            idx += 1
        header.append(int(data[start:idx]))
    width, height, _maxval = header
    idx += 1  # exactly one whitespace byte after maxval
    return width, height, data[idx : idx + width * height * 3]


def _region_peak_diff(a: tuple, b: tuple, box: tuple[float, float, float, float]) -> int:
    """Peak absolute per-channel difference between two frames over a fractional box.

    Text is sparse (a bright glyph on a solid field), so a mean over a wide region
    dilutes to near zero; the peak reliably answers "did a pixel here change?".
    """
    wa, ha, pa = a
    wb, hb, pb = b
    assert (wa, ha) == (wb, hb)
    x0, y0 = int(box[0] * wa), int(box[1] * ha)
    x1, y1 = int(box[2] * wa), int(box[3] * ha)
    peak = 0
    for y in range(y0, y1):
        base = (y * wa + x0) * 3
        for off in range((x1 - x0) * 3):
            diff = abs(pa[base + off] - pb[base + off])
            if diff > peak:
                peak = diff
    return peak
