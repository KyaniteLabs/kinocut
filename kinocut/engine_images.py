"""Image sequence creation operation for the FFmpeg engine."""

from __future__ import annotations

import io
import math
import os
import re
import shutil
import struct
import tempfile

from .engine_runtime_utils import _build_edit_result, _movflags_args, _quality_args, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _atomic_output, _run_ffmpeg, _run_ffprobe_json
from .errors import InputFileError, MCPVideoError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .limits import MAX_EXPORT_FRAMES_FPS, MAX_IMAGE_SEQUENCE_FRAMES, MAX_IMAGE_SEQUENCE_LIST_BYTES
from .models import EditResult

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# ASCII digits only, bounded so int() never meets Python's digit-count limit.
_RATIONAL_FPS_PATTERN = re.compile(r"^\s*([0-9]{1,18})\s*/\s*([0-9]{1,18})\s*$")
# Write one image to a literal path: without -update the image2 muxer expands
# "%" sequences in the output name, which breaks a temp directory containing "%".
_SINGLE_IMAGE_OUTPUT_ARGS = ("-frames:v", "1", "-update", "1")


def create_from_images(
    images: list[str] | None = None,
    output_path: str | None = None,
    fps: float | int | str = 30.0,
    *,
    list_file: str | None = None,
) -> EditResult:
    """Create a frame-exact video from a sequence of images.

    Each input image becomes exactly one output frame. ``fps`` accepts a
    positive integer, a positive decimal, or a rational string such as
    ``"30000/1001"``. When ``list_file`` is supplied, it is a UTF-8 file with
    one image path per line; blank lines are ignored.
    """
    inputs = _resolve_inputs(images, list_file)
    _, fps_arg = _coerce_fps(fps)
    validated_images = [_validate_input_path(img) for img in inputs]

    output = output_path or _auto_output(validated_images[0], "from_images")
    _validate_output_path(output)
    with _timed_operation() as timing, _atomic_output(output) as staged:
        tmpdir = tempfile.mkdtemp(prefix="mcp_video_imgseq_")
        try:
            link_dir = os.path.join(tmpdir, "linked")
            os.mkdir(link_dir)
            if _link_even_png_sequence(validated_images, link_dir):
                sequence_dir, extension = link_dir, ".png"
            else:
                normalized = _normalize_images(validated_images, tmpdir)
                sequence_dir, extension = tmpdir, os.path.splitext(normalized[0])[1]
            _run_ffmpeg(
                [
                    # A decode error in any input must fail the export, never drop a frame.
                    "-xerror",
                    "-framerate",
                    fps_arg,
                    "-start_number",
                    "0",
                    "-i",
                    _sequence_pattern(sequence_dir, extension),
                    "-c:v",
                    "libx264",
                    *_quality_args(),
                    "-frames:v",
                    str(len(validated_images)),
                    "-pix_fmt",
                    "yuv420p",
                    *_movflags_args(staged),
                    staged,
                ]
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        # Published only if this holds; on failure the staged file is discarded.
        _verify_output_frame_count(staged, len(validated_images))

    return _build_edit_result(
        output,
        "create_from_images",
        timing,
    )


def _verify_output_frame_count(path: str, expected: int) -> None:
    """Fail unless the encoded video holds exactly ``expected`` frames.

    The container's frame count is used when present; otherwise the video
    stream is decoded and counted.
    """
    actual = _video_frame_count(_run_ffprobe_json(path))
    if actual is None:
        actual = _video_frame_count(_run_ffprobe_json(path, count_frames=True), key="nb_read_frames")
    if actual != expected:
        raise MCPVideoError(
            f"create_from_images encoded {actual} frames for {expected} input images",
            error_type="processing_error",
            code="frame_count_mismatch",
        )


def _video_frame_count(info: dict, key: str = "nb_frames") -> int | None:
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            value = str(stream.get(key, ""))
            return int(value) if value.isdigit() else None
    return None


def _resolve_inputs(images: list[str] | None, list_file: str | None) -> list[str]:
    if list_file is not None and images:
        raise MCPVideoError(
            "Provide either images or list_file, not both",
            error_type="validation_error",
            code="conflicting_inputs",
        )
    if list_file is not None:
        images = _read_list_file(list_file)
    if not images:
        raise MCPVideoError(
            "No images provided",
            error_type="validation_error",
            code="empty_images",
        )
    if len(images) > MAX_IMAGE_SEQUENCE_FRAMES:
        raise _too_many_images()
    return list(images)


def _too_many_images() -> MCPVideoError:
    return MCPVideoError(
        f"create_from_images accepts at most {MAX_IMAGE_SEQUENCE_FRAMES} images",
        error_type="validation_error",
        code="too_many_images",
    )


def _read_list_file(list_file: str) -> list[str]:
    """Read one image path per non-blank line, bounded before any image is validated."""
    resolved = _validate_input_path(list_file)
    try:
        size = os.path.getsize(resolved)
    except OSError as exc:
        raise InputFileError(resolved, f"Cannot read list file: {exc}") from None
    if size > MAX_IMAGE_SEQUENCE_LIST_BYTES:
        raise _list_file_too_large()
    try:
        with open(resolved, "rb") as handle:
            # Bounded read: a file that grows after the size check still cannot exceed the limit.
            data = handle.read(MAX_IMAGE_SEQUENCE_LIST_BYTES + 1)
    except OSError as exc:
        raise InputFileError(resolved, f"Cannot read list file: {exc}") from None
    if len(data) > MAX_IMAGE_SEQUENCE_LIST_BYTES:
        raise _list_file_too_large()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InputFileError(resolved, "list file is not valid UTF-8") from exc
    paths: list[str] = []
    for line in io.StringIO(text, newline=None):
        entry = line.strip()
        if not entry:
            continue
        if len(paths) == MAX_IMAGE_SEQUENCE_FRAMES:
            raise _too_many_images()
        paths.append(entry)
    return paths


def _list_file_too_large() -> MCPVideoError:
    return MCPVideoError(
        f"list file exceeds {MAX_IMAGE_SEQUENCE_LIST_BYTES} bytes",
        error_type="validation_error",
        code="list_file_too_large",
    )


def _format_fps_for_ffmpeg(fps: float | int | str) -> str:
    """Serialize FPS without rounding non-integer values before FFmpeg sees them."""
    return _coerce_fps(fps)[1]


def _coerce_fps(fps: float | int | str) -> tuple[float, str]:
    """Validate an FPS value and return its numeric and FFmpeg-serialized forms."""
    value, rate = _parse_fps(fps)
    if value > MAX_EXPORT_FRAMES_FPS:
        raise MCPVideoError(
            f"fps must not exceed {MAX_EXPORT_FRAMES_FPS}, got {fps}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return value, rate


def _parse_fps(fps: float | int | str) -> tuple[float, str]:
    """Parse a positive finite FPS (number or ``num/den``) without the range bound."""
    if isinstance(fps, bool):
        raise _invalid_fps(fps)
    if isinstance(fps, str):
        match = _RATIONAL_FPS_PATTERN.match(fps)
        if match:
            numerator, denominator = int(match.group(1)), int(match.group(2))
            if denominator == 0:
                raise _invalid_fps(fps)
            try:
                value = numerator / denominator
            except OverflowError as exc:
                raise _invalid_fps(fps) from exc
            divisor = math.gcd(numerator, denominator)
            rate = f"{numerator // divisor}/{denominator // divisor}"
        else:
            value = _to_float(fps)
            rate = _format_numeric_rate(value)
    else:
        value = _to_float(fps)
        rate = _format_numeric_rate(value)

    if value <= 0 or not math.isfinite(value):
        raise _invalid_fps(fps)
    return value, rate


def _to_float(fps: float | int | str) -> float:
    try:
        return float(fps)
    except (OverflowError, TypeError, ValueError) as exc:
        raise _invalid_fps(fps) from exc


def _invalid_fps(fps: float | int | str) -> MCPVideoError:
    return MCPVideoError(
        f"fps must be a positive finite number, got {fps}",
        error_type="validation_error",
        code="invalid_parameter",
    )


def _format_numeric_rate(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return repr(value)


def _png_size(path: str) -> tuple[int, int] | None:
    """Read PNG dimensions from the file header without invoking FFmpeg."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != _PNG_SIGNATURE or header[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", header[16:24])
    if width <= 0 or height <= 0:
        return None
    return width, height


def _sequence_pattern(sequence_dir: str, extension: str) -> str:
    """Return the contiguous image2 pattern consumed by FFmpeg.

    image2 expands ``%`` sequences anywhere in the pattern, so a literal ``%``
    in the directory (for example in TMP) is escaped as ``%%``.
    """
    return os.path.join(sequence_dir.replace("%", "%%"), f"frame_%08d{extension}")


def _link_even_png_sequence(images: list[str], link_dir: str) -> bool:
    """Expose even-dimension PNGs as a contiguous sequence without re-encoding.

    The image paths arrive already resolved by ``_validate_input_path``. Each
    one is hard-linked into ``link_dir`` first and its header is then read
    through that link, so a path that is renamed over or replaced after the
    check cannot change the checked file, and a path replaced by a symlink after
    validation is refused. A hard link shares the inode, so a concurrent writer
    rewriting the same file in place can still change its bytes; that case is
    not defended here, exactly as for any other FFmpeg input.

    Returns False, leaving the caller to re-encode the whole sequence with the
    normalizer, as soon as an input is a symlink, is not an even-dimension PNG,
    or cannot be hard-linked (another filesystem, missing privilege, or the
    filesystem's per-file link limit, 1023 on NTFS, for a frame repeated that
    often). Linking updates the inputs' link count and ctime but never their
    contents; inputs are never copied or symlinked. ``link_dir`` must be private
    to this call: the normalizer writes elsewhere, so it can never write through
    a link into an input.
    """
    for index, image in enumerate(images):
        target = os.path.join(link_dir, f"frame_{index:08d}.png")
        if os.path.islink(image) or not _hard_link(image, target):
            return False
        if os.path.islink(target) or not os.path.isfile(target):
            return False
        size = _png_size(target)
        if size is None or size[0] % 2 or size[1] % 2:
            return False
    return True


def _hard_link(source: str, target: str) -> bool:
    """Hard-link ``source`` itself, never a file a symlink points to."""
    try:
        if os.link in os.supports_follow_symlinks:
            os.link(source, target, follow_symlinks=False)
        else:
            os.link(source, target)
    except (OSError, NotImplementedError):
        return False
    return True


def _normalize_images(images: list[str], tmpdir: str) -> list[str]:
    has_png = any(img.lower().endswith(".png") for img in images)
    img_format = "png" if has_png else "jpg"
    ext = f".{img_format}"

    normalized: list[str] = []
    for i, img in enumerate(images):
        norm_path = os.path.join(tmpdir, f"frame_{i:08d}{ext}")
        if img_format == "png":
            _run_ffmpeg(
                [
                    "-y",
                    "-i",
                    img,
                    "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v",
                    "png",
                    *_SINGLE_IMAGE_OUTPUT_ARGS,
                    norm_path,
                ]
            )
        else:
            _run_ffmpeg(
                [
                    "-y",
                    "-i",
                    img,
                    "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-q:v",
                    "2",
                    *_SINGLE_IMAGE_OUTPUT_ARGS,
                    norm_path,
                ]
            )
        normalized.append(norm_path)
    return normalized
