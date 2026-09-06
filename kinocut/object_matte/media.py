"""Stream decode, scratch caps, and frame-count refusal (ported from Forgejo #412)."""

from __future__ import annotations

import logging
import select
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from PIL import Image, ImageOps

from ..defaults import DEFAULT_FPS, DEFAULT_OBJECT_MATTE_TIMEOUT, OBJECT_MATTE_STILL_SUFFIXES
from ..errors import MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _get_video_duration, _run_ffprobe_json, _validate_input_path
from ..limits import MAX_OBJECT_MATTE_FRAMES, MAX_OBJECT_MATTE_SCRATCH_BYTES

logger = logging.getLogger(__name__)
_DOCS = "docs/PRODUCT_MATTE.md"


def is_still(path: str) -> bool:
    return Path(path).suffix.lower() in OBJECT_MATTE_STILL_SUFFIXES


def apply_alpha(image: Image.Image, mask: Image.Image, *, invert: bool = False) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = mask.convert("L").resize(rgba.size, Image.Resampling.NEAREST)
    if invert:
        alpha = ImageOps.invert(alpha)
    rgba.putalpha(alpha)
    return rgba


def load_still(path: str) -> Image.Image:
    return Image.open(_validate_input_path(path)).convert("RGB")


def _parse_rate(rate: object) -> float | None:
    text = str(rate or "")
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            denom = float(den)
            value = float(num) / denom if denom else 0.0
        else:
            value = float(text)
    except ValueError:
        return None
    return value if value > 0 else None


def _probe_video_meta(input_path: str) -> tuple[float, int | None, int, int]:
    payload = _run_ffprobe_json(input_path)
    fps = float(DEFAULT_FPS)
    frames: int | None = None
    width = 0
    height = 0
    for stream in payload.get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        parsed = _parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
        if parsed:
            fps = parsed
        raw = stream.get("nb_frames")
        if raw not in {None, "", "N/A"}:
            try:
                frames = int(raw)
            except ValueError:
                frames = None
        try:
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
        except (TypeError, ValueError):
            width, height = 0, 0
        break
    if width < 1 or height < 1:
        raise MCPVideoError(
            "Object-matte video has no usable width/height",
            error_type="validation_error",
            code="invalid_parameter",
            docs_url=_DOCS,
        )
    if frames is None:
        try:
            duration = _get_video_duration(input_path)
        except (MCPVideoError, ProcessingError):
            duration = 0.0
        if duration > 0:
            frames = int(duration * fps + 0.5)
    return fps, frames, width, height


def refuse_overlong_video(input_path: str) -> tuple[float, int, int, int]:
    """Known frame count required before decode or weight download."""
    fps, frames, width, height = _probe_video_meta(input_path)
    if frames is None or frames < 1:
        raise MCPVideoError(
            "Object-matte needs a known frame count before decode",
            error_type="resource_error",
            code="frame_count_unknown",
            docs_url=_DOCS,
        )
    if frames > MAX_OBJECT_MATTE_FRAMES:
        raise MCPVideoError(
            f"Object-matte frame count {frames} exceeds {MAX_OBJECT_MATTE_FRAMES}",
            error_type="resource_error",
            code="frame_count_too_large",
            docs_url=_DOCS,
        )
    return fps, frames, width, height


def estimate_scratch_bytes(width: int, height: int, frames: int, *, hole: bool) -> int:
    planes = 2 if hole else 1
    return width * height * 4 * max(frames, 1) * planes


def charge_scratch(used: int, added: int, cap: int | None = None) -> int:
    limit = MAX_OBJECT_MATTE_SCRATCH_BYTES if cap is None else cap
    total = used + added
    if added < 0 or total > limit:
        raise MCPVideoError(
            f"Object-matte scratch budget {limit} bytes exceeded",
            error_type="resource_error",
            code="scratch_budget_exceeded",
            docs_url=_DOCS,
        )
    return total


def refuse_scratch(width: int, height: int, frames: int, hole: bool, work_dir: Path) -> None:
    estimate = estimate_scratch_bytes(width, height, frames, hole=hole)
    charge_scratch(0, estimate)
    free = shutil.disk_usage(work_dir).free
    if estimate > free:
        raise MCPVideoError(
            f"Object-matte needs about {estimate} free bytes, disk has {free}",
            error_type="resource_error",
            code="insufficient_disk",
            docs_url=_DOCS,
        )


def decode_video_argv(input_path: str, width: int, height: int) -> list[str]:
    del width, height
    return [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_path,
        "-frames:v",
        str(MAX_OBJECT_MATTE_FRAMES + 1),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]


def _read_exact(stream, size: int, deadline: float) -> bytes | None:
    chunks: list[bytes] = []
    got = 0
    while got < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MCPVideoError(
                f"Object-matte exceeded {DEFAULT_OBJECT_MATTE_TIMEOUT}s",
                error_type="processing_error",
                code="object_matte_timeout",
                docs_url=_DOCS,
            )
        try:
            ready, _, _ = select.select([stream], [], [], remaining)
        except (OSError, TypeError, ValueError):
            ready = [stream]
        if not ready:
            raise MCPVideoError(
                f"Object-matte exceeded {DEFAULT_OBJECT_MATTE_TIMEOUT}s",
                error_type="processing_error",
                code="object_matte_timeout",
                docs_url=_DOCS,
            )
        piece = stream.read(size - got)
        if not piece:
            if got == 0:
                return None
            raise MCPVideoError(
                "Object-matte decode ended on a partial frame",
                error_type="processing_error",
                code="object_matte_decode_failed",
                docs_url=_DOCS,
            )
        chunks.append(piece)
        got += len(piece)
    return b"".join(chunks)


def iter_video_rgb(input_path: str, width: int, height: int, deadline: float | None = None) -> Iterator[Image.Image]:
    frame_bytes = width * height * 3
    ends = time.monotonic() + DEFAULT_OBJECT_MATTE_TIMEOUT if deadline is None else deadline
    proc = subprocess.Popen(  # noqa: S603
        decode_video_argv(input_path, width, height),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    count = 0
    try:
        if proc.stdout is None:
            raise MCPVideoError(
                "Object-matte decode produced no stdout",
                error_type="processing_error",
                code="object_matte_decode_failed",
                docs_url=_DOCS,
            )
        while True:
            buf = _read_exact(proc.stdout, frame_bytes, ends)
            if buf is None:
                break
            count += 1
            if count > MAX_OBJECT_MATTE_FRAMES:
                raise MCPVideoError(
                    f"Object-matte frame count {count} exceeds {MAX_OBJECT_MATTE_FRAMES}",
                    error_type="resource_error",
                    code="frame_count_too_large",
                    docs_url=_DOCS,
                )
            yield Image.frombytes("RGB", (width, height), buf)
        remaining = max(0.1, ends - time.monotonic())
        try:
            rc = proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise MCPVideoError(
                f"Object-matte exceeded {DEFAULT_OBJECT_MATTE_TIMEOUT}s",
                error_type="processing_error",
                code="object_matte_timeout",
                docs_url=_DOCS,
            ) from None
        if rc != 0:
            raise MCPVideoError(
                f"Object-matte ffmpeg decode failed: {rc}",
                error_type="processing_error",
                code="object_matte_decode_failed",
                docs_url=_DOCS,
            )
        if count == 0:
            raise MCPVideoError(
                "Object-matte extract produced no frames",
                error_type="processing_error",
                code="object_matte_no_frames",
                docs_url=_DOCS,
            )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def iter_source_frames(
    input_path: str,
    width: int | None = None,
    height: int | None = None,
    deadline: float | None = None,
) -> Iterator[Image.Image]:
    if is_still(input_path):
        yield load_still(input_path)
        return
    if width is None or height is None:
        _fps, _frames, width, height = _probe_video_meta(input_path)
    yield from iter_video_rgb(input_path, width, height, deadline=deadline)
