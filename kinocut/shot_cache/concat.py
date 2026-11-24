"""Strict, video-only stream-copy assembly."""

import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from ..bounded_process import run_bounded
from ..engine_runtime_utils import _ffprobe
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _run_ffmpeg
from ..publication import atomic_output


_FIELDS = (
    "codec_type",
    "codec_name",
    "pix_fmt",
    "r_frame_rate",
    "avg_frame_rate",
    "sample_aspect_ratio",
    "time_base",
    "width",
    "height",
    "nb_read_frames",
)
_MESSAGES = {
    name: f"Concat check failed: {name}" for name in (*_FIELDS, "probe", "stream layout", "clip count", "frame_count")
}


def _mismatch(field):
    raise MCPVideoError(_MESSAGES[field], code="concat_stream_mismatch")


def _probe(path):
    fields = ",".join(_FIELDS)
    result = run_bounded(
        [
            _ffprobe(),
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            f"stream={fields}",
            "-of",
            "json",
            "-i",
            str(Path(path).absolute()),
        ],
        timeout=600,
    )
    if result.returncode or result.stderr:
        _mismatch("probe")
    streams = json.loads(result.stdout).get("streams", [])
    if [stream.get("codec_type") for stream in streams] != ["video"]:
        _mismatch("stream layout")
    stream = streams[0]
    for field in _FIELDS:
        if stream.get(field) in (None, "unknown", "N/A", "", 0, "0/0"):
            _mismatch(field)
    for field in ("r_frame_rate", "avg_frame_rate", "sample_aspect_ratio", "time_base"):
        try:
            stream[field] = Fraction(stream[field].replace(":", "/"))
        except (ValueError, ZeroDivisionError):
            _mismatch(field)
    return stream, int(stream.pop("nb_read_frames"))


def verify_concat_compatibility(clip_paths, expected_frame_counts=None) -> int:
    paths = [_checked_path(path) for path in clip_paths]
    if not paths:
        raise ValueError("At least one clip is required")
    expected = None if expected_frame_counts is None else tuple(expected_frame_counts)
    if expected is not None and len(paths) != len(expected):
        _mismatch("clip count")
    reference = None
    total = 0
    for index, path in enumerate(paths):
        stream, frames = _probe(path)
        if reference is None:
            reference = stream
        for field, value in reference.items():
            if stream[field] != value:
                _mismatch(field)
        if expected is not None and frames != expected[index]:
            _mismatch("frame_count")
        total += frames
    return total


def _checked_path(path: str | Path) -> Path:
    def check(name: str) -> None:
        if any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ValueError("Concat filenames cannot contain ASCII control characters")

    check(str(path))
    resolved = Path(path).resolve()
    check(str(resolved))
    return resolved


def _manifest_entry(path: Path) -> str:
    return "file '" + str(path).replace("'", "'\\''") + "'\n"


def splice_shots_lossless(clip_paths, output_path, expected_frame_counts=None) -> int:
    paths = tuple(_checked_path(path) for path in clip_paths)
    total = verify_concat_compatibility(paths, expected_frame_counts)
    with TemporaryDirectory() as temp, atomic_output(str(output_path)) as staged:
        manifest = Path(temp) / "shots.ffconcat"
        manifest.write_text("ffconcat version 1.0\n" + "".join(map(_manifest_entry, paths)), encoding="utf-8")
        _run_ffmpeg(
            ["-v", "error", "-f", "concat", "-safe", "0", "-i", str(manifest), "-map", "0:v:0", "-c", "copy", staged]
        )
        verify_concat_compatibility([staged], [total])
    return total
