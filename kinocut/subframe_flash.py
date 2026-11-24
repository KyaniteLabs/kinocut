"""Opt-in experimental light timing. No timeline or standard flash uses this module."""

import math
import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import BinaryIO

from .ffmpeg_helpers import _run_ffmpeg
from .publication import atomic_output


def _validate(fps: float, peak: float) -> None:
    if not math.isfinite(fps) or fps <= 0 or not 0 <= peak <= 1:
        raise ValueError("fps must be positive and finite; peak_brightness must be in [0, 1]")


def compute_subframe_flash_split(
    target_onset_ms: float, fps: float = 30.0, peak_brightness: float = 1.0
) -> dict[int, float]:
    """Return normalized brightness at the two frame indices surrounding the onset."""
    _validate(fps, peak_brightness)
    if not math.isfinite(target_onset_ms) or target_onset_ms < 0:
        raise ValueError("target_onset_ms must be finite and nonnegative")
    position = target_onset_ms * fps / 1000.0
    if not math.isfinite(position):
        raise ValueError("Flash frame position must be finite")
    index = math.floor(position)
    fraction = position - index
    return {index: (1 - fraction) * peak_brightness, index + 1: fraction * peak_brightness}


@contextmanager
def _raw_input() -> Iterator[tuple[BinaryIO, str, tuple[int, ...]]]:
    if os.name == "posix":
        with TemporaryFile() as raw:
            yield raw, f"pipe:{raw.fileno()}", (raw.fileno(),)
    else:
        with TemporaryDirectory() as temp:
            path = Path(temp) / "flash.gray"
            with path.open("w+b") as raw:
                yield raw, str(path), ()


def _render(output: str | Path, levels: bytearray, fps: float, width: int, height: int) -> str:
    if not all(type(value) is int and value > 0 for value in (width, height)) or not levels:
        raise ValueError("Dimensions and frame count must be positive integers")
    with atomic_output(str(output)) as staged, _raw_input() as (raw, source, descriptors):
        raw.write(levels)
        raw.seek(0)
        _run_ffmpeg(
            [
                "-v",
                "error",
                "-f",
                "rawvideo",
                "-pixel_format",
                "gray",
                "-video_size",
                "1x1",
                "-framerate",
                str(fps),
                "-i",
                source,
                "-vf",
                f"scale={width}:{height}:flags=neighbor,setsar=1",
                "-threads",
                "1",
                "-c:v",
                "png",
                "-pix_fmt",
                "gray",
                staged,
            ],
            pass_fds=descriptors,
        )
    return str(output)


def render_subframe_flash(
    output_path: str | Path,
    *,
    duration_s: float = 1.0,
    fps: float = 30.0,
    width: int = 320,
    height: int = 180,
    target_onset_ms: float = 500.0,
    peak_brightness: float = 1.0,
) -> str:
    split = compute_subframe_flash_split(target_onset_ms, fps, peak_brightness)
    if not math.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("duration_s must be positive and finite")
    frames = duration_s * fps
    if not math.isfinite(frames):
        raise ValueError("Flash frame count must be finite")
    levels = bytearray(round(frames))
    if min(split) >= len(levels) or (max(split) >= len(levels) and split[max(split)] > 0):
        raise ValueError("Flash extends beyond the clip")
    for index, value in split.items():
        if index < len(levels):
            levels[index] = round(255 * value)
    return _render(output_path, levels, fps, width, height)


def render_subframe_flash_strip(
    output_path: str | Path,
    *,
    offsets: Iterable[float] = (0.0, 0.25, 0.5, 0.75),
    fps: float = 30.0,
    width: int = 320,
    height: int = 180,
    peak_brightness: float = 1.0,
) -> str:
    _validate(fps, peak_brightness)
    levels = bytearray()
    segment = max(3, round(fps))
    for offset in offsets:
        if not 0 <= offset < 1:
            raise ValueError("Strip offsets must be fractions in [0, 1)")
        start = len(levels) + segment // 2
        levels.extend(bytes(segment))
        levels[start] = round(255 * (1 - offset) * peak_brightness)
        levels[start + 1] = round(255 * offset * peak_brightness)
    return _render(output_path, levels, fps, width, height)
