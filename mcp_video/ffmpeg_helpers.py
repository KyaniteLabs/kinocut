"""Shared FFmpeg helper functions.

Centralises duplicated utilities used across engine modules so there is a
single authoritative copy of each helper.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import threading
from collections.abc import Callable
from typing import Any

from .errors import InputFileError, MCPVideoError, ProcessingError, parse_ffmpeg_error
from .limits import DEFAULT_FFMPEG_TIMEOUT, FFPROBE_TIMEOUT, MAX_FILE_SIZE_MB

_BLOCKED_OUTPUT_PREFIXES = (
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/private/etc",
    "/private/var/db",
    "/private/var/log",
    "/private/var/root",
    "/proc",
    "/root",
    "/sbin",
    "/sys",
    "/System",
    "/usr",
    "/var/db",
    "/var/log",
    "/var/root",
)
_SENSITIVE_HOME_PARTS = {".aws", ".azure", ".config", ".docker", ".gnupg", ".kube", ".ssh"}
_SAFE_EXISTING_OUTPUT_SUFFIXES = {
    ".aac",
    ".ass",
    ".avi",
    ".csv",
    ".flac",
    ".gif",
    ".jpg",
    ".jpeg",
    ".json",
    ".m3u8",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".png",
    ".srt",
    ".ts",
    ".txt",
    ".vtt",
    ".wav",
    ".webm",
    ".webp",
}


def _validate_input_path(path: str) -> str:
    """Validate and resolve a file path. Rejects null bytes, symlinks, and oversize files."""
    if "\x00" in path:
        raise InputFileError(path, "Path contains null bytes")
    resolved = os.path.realpath(path)
    if not os.path.isfile(resolved):
        raise InputFileError(resolved)
    try:
        size_mb = os.path.getsize(resolved) / (1024 * 1024)
    except OSError as e:
        raise InputFileError(resolved, f"Cannot read file size: {e}") from None
    if size_mb > MAX_FILE_SIZE_MB:
        raise InputFileError(
            resolved,
            f"File size ({size_mb:.1f} MB) exceeds maximum of {MAX_FILE_SIZE_MB} MB",
        )
    return resolved


def _validate_project_path(path: str) -> str:
    """Validate a project directory path."""
    if "\x00" in path:
        raise InputFileError(path, "Path contains null bytes")
    resolved = os.path.realpath(path)
    if not os.path.isdir(resolved):
        raise InputFileError(resolved, "Directory does not exist")
    return resolved


_SAFE_EXISTING_ARTIFACT_SUFFIXES = frozenset({".json"})


def _validate_write_path(
    path: str,
    *,
    allowed_existing_suffixes: frozenset[str],
    label: str,
) -> str:
    """Shared write-path guard used by output-media and artifact writers.

    Blocks null bytes, ``..`` traversal, symlink targets, system directories,
    and sensitive home dotfiles. When the target already exists, refuses to
    overwrite it unless its suffix is in ``allowed_existing_suffixes`` (media
    suffixes for renders; ``.json`` only for provenance artifacts).
    """
    if "\x00" in path:
        raise MCPVideoError(
            f"{label} contains null bytes: {path!r}",
            error_type="validation_error",
            code="invalid_output_path",
        )
    raw_parts = re.split(r"[\\/]+", path)
    if ".." in raw_parts:
        raise MCPVideoError(
            f"{label} contains directory traversal: {path!r}",
            error_type="validation_error",
            code="invalid_output_path",
        )
    if os.path.islink(path):
        raise MCPVideoError(
            f"{label} resolves through a symlink: {path!r}",
            error_type="validation_error",
            code="unsafe_path",
        )

    resolved = os.path.realpath(path)
    if any(resolved == prefix or resolved.startswith(prefix + os.sep) for prefix in _BLOCKED_OUTPUT_PREFIXES):
        raise MCPVideoError(
            f"{label} escapes safe directory: {path}",
            error_type="validation_error",
            code="unsafe_path",
        )

    home = os.path.realpath(os.path.expanduser("~"))
    if resolved == home or resolved.startswith(home + os.sep):
        rel_parts = set(os.path.relpath(resolved, home).split(os.sep))
        if rel_parts & _SENSITIVE_HOME_PARTS:
            raise MCPVideoError(
                f"{label} targets a sensitive home directory: {path}",
                error_type="validation_error",
                code="unsafe_path",
            )

    if os.path.isdir(resolved):
        return path

    if os.path.exists(resolved):
        suffix = os.path.splitext(resolved)[1].lower()
        if suffix not in allowed_existing_suffixes:
            raise MCPVideoError(
                f"Refusing to overwrite existing file at {label.lower()}: {path}",
                error_type="validation_error",
                code="unsafe_path",
            )
    return path


def _validate_output_path(path: str) -> str:
    """Validate an output path before FFmpeg writes with ``-y``.

    mcp-video intentionally lets users write normal media artifacts around their
    projects and temp directories. It must not overwrite system files, symlink
    targets, sensitive home dotfiles, or obviously non-media source/config files.
    """
    return _validate_write_path(
        path, allowed_existing_suffixes=_SAFE_EXISTING_OUTPUT_SUFFIXES, label="Output path"
    )


def _validate_artifact_path(path: str) -> str:
    """Validate a provenance-artifact write path (plan/receipt JSON).

    Same traversal / symlink / system-dir / sensitive-dotfile guard as
    ``_validate_output_path`` but stricter on overwrite: a workflow plan or
    receipt may only overwrite an existing ``.json`` artifact, never a media
    file or any other on-disk file.
    """
    return _validate_write_path(
        path, allowed_existing_suffixes=_SAFE_EXISTING_ARTIFACT_SUFFIXES, label="Artifact path"
    )


def _run_command(cmd: list[str], timeout: int = DEFAULT_FFMPEG_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run an arbitrary command with timeout and error handling.

    Bare ``ffmpeg``/``ffprobe`` names are replaced with the resolved runtime
    binaries so every code path finds FFmpeg the same way.
    """
    from .engine_runtime_utils import _ffmpeg, _ffprobe

    if cmd and cmd[0] == "ffmpeg":
        cmd = [_ffmpeg(), *cmd[1:]]
    elif cmd and cmd[0] == "ffprobe":
        cmd = [_ffprobe(), *cmd[1:]]
    # Ensure output directory exists — find the last non-flag argument (the
    # output file), never considering cmd[0] (the binary itself).
    for arg in reversed(cmd[1:]):
        if not arg.startswith("-"):
            out_dir = os.path.dirname(arg)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            break
    cmd_str = " ".join(cmd)
    try:
        # cmd is always a list built from trusted internal ffmpeg/ffprobe paths; no shell=True
        result = subprocess.run(  # noqa: S603
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise ProcessingError(cmd_str, -1, f"FFmpeg command timed out after {timeout}s") from None
    if result.returncode != 0:
        raise ProcessingError(cmd_str, result.returncode, result.stderr)
    return result


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg with raw arguments; the resolved binary and ``-y`` are prepended.

    The previous dual-mode signature (raw args OR a full command) silently
    changed binary resolution and ``-y`` behavior based on the first element.
    """
    from .engine_runtime_utils import _ffmpeg

    if args and args[0] in {"ffmpeg", "ffprobe"}:
        raise ValueError(
            "_run_ffmpeg takes raw FFmpeg arguments (the resolved binary and -y are "
            "prepended); use _run_command for full ffmpeg/ffprobe command lists"
        )
    cmd = [_ffmpeg(), "-y", *args]
    try:
        # cmd is always a list-form ffmpeg invocation; no shell=True
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise ProcessingError(" ".join(cmd), -1, f"FFmpeg command timed out after {DEFAULT_FFMPEG_TIMEOUT}s") from e
    if proc.returncode != 0:
        raise parse_ffmpeg_error(proc.stderr, command=cmd)
    return proc


_TIME_RE = re.compile(r"time=(\d+:\d+:\d+\.\d+)")


def _parse_ffmpeg_time(time_str: str) -> float:
    """Parse FFmpeg time= value (HH:MM:SS.xx) to seconds."""
    m = re.match(r"(\d+):(\d+):(\d+)\.(\d+)", time_str)
    if not m:
        return 0.0
    frac = m.group(4)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(frac) / (10 ** len(frac))


def _run_ffmpeg_with_progress(
    args: list[str],
    estimated_duration: float | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg with real-time progress reporting.

    Parses FFmpeg stderr for time= output and calls on_progress(percent).
    Falls back to _run_ffmpeg if estimated_duration is not provided.
    """
    from .engine_runtime_utils import _ffmpeg

    if estimated_duration is None or estimated_duration <= 0 or on_progress is None:
        return _run_ffmpeg(args)

    cmd = [_ffmpeg(), "-y", *args]
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    stderr_lines: list[str] = []
    progress_errors: list[BaseException] = []
    _MAX_STDERR_LINES = 10_000
    _MAX_STDERR_BYTES = 10_000_000  # ~10 MB hard cap
    _stderr_bytes = 0

    def _read_stderr() -> None:
        nonlocal _stderr_bytes
        while proc.stderr is not None:
            line = proc.stderr.readline()
            if not line:
                break
            line_bytes = len(line.encode("utf-8", errors="replace"))
            if len(stderr_lines) < _MAX_STDERR_LINES and _stderr_bytes + line_bytes <= _MAX_STDERR_BYTES:
                stderr_lines.append(line)
                _stderr_bytes += line_bytes

            match = _TIME_RE.search(line)
            if match:
                current_time = _parse_ffmpeg_time(match.group(1))
                pct = min(100.0, (current_time / estimated_duration) * 100)
                try:
                    on_progress(pct)
                except BaseException as exc:  # propagate callback failures from the reader thread
                    progress_errors.append(exc)
                    if proc.poll() is None:
                        proc.terminate()
                    break

    reader = threading.Thread(target=_read_stderr)
    reader.start()

    try:
        proc.wait(timeout=DEFAULT_FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        reader.join(timeout=5)
        raise ProcessingError(" ".join(cmd), -1, f"FFmpeg command timed out after {DEFAULT_FFMPEG_TIMEOUT}s") from None
    finally:
        reader.join(timeout=5)

    stderr = "".join(stderr_lines)
    if progress_errors:
        raise progress_errors[0]
    if proc.returncode != 0:
        raise parse_ffmpeg_error(stderr, command=cmd)

    # Report 100% on success
    on_progress(100.0)

    return subprocess.CompletedProcess(
        cmd,
        proc.returncode,
        "",
        stderr,
    )


def _build_ffmpeg_cmd(
    *inputs: str,
    output_path: str,
    video_codec: str = "libx264",
    video_filter: str | None = None,
    audio_codec: str | None = "aac",
    audio_filter: str | None = None,
    audio_bitrate: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
    extra: list[str] | None = None,
    movflags: bool = True,
) -> list[str]:
    """Build a standard FFmpeg argument list for video encoding.

    Eliminates the repeated construction of::

        ["-i", input, "-c:v", "libx264", *_quality_args(),
         "-c:a", "aac", "-b:a", DEFAULT_AUDIO_BITRATE,
         *_movflags_args(output), output]

    found across 15+ engine functions.

    Args:
        *inputs: Input file paths. Each becomes a separate ``-i`` argument.
        output_path: Output file path.
        video_codec: Video codec (e.g. ``libx264``, ``copy``, ``prores_ks``).
                     Use ``None`` to omit ``-c:v`` entirely.
        video_filter: Video filter string. Adds ``-vf`` flag.
        audio_codec: Audio codec (e.g. ``aac``, ``copy``, ``pcm_s16le``).
                     Use ``None`` to omit ``-c:a`` entirely.
        audio_filter: Audio filter string. Adds ``-af`` flag.
        audio_bitrate: Audio bitrate (e.g. ``128k``). Defaults to
                       ``DEFAULT_AUDIO_BITRATE`` when ``audio_codec == "aac"``.
        crf: Constant Rate Factor. Passed to ``_quality_args()``.
        preset: Encoding preset. Passed to ``_quality_args()``.
        extra: Extra arguments inserted before movflags/output.
        movflags: Whether to append ``-movflags +faststart`` for mp4/mov.
    """
    from .defaults import DEFAULT_AUDIO_BITRATE
    from .engine_runtime_utils import _movflags_args, _quality_args

    cmd: list[str] = []
    for inp in inputs:
        cmd.extend(["-i", inp])

    if video_filter is not None:
        cmd.extend(["-vf", video_filter])
    if audio_filter is not None:
        cmd.extend(["-af", audio_filter])

    if video_codec is not None:
        cmd.extend(["-c:v", video_codec])
        if video_codec != "copy":
            cmd.extend(_quality_args(crf=crf, preset=preset))

    if audio_codec is not None:
        cmd.extend(["-c:a", audio_codec])
        if audio_codec == "aac":
            cmd.extend(["-b:a", audio_bitrate or DEFAULT_AUDIO_BITRATE])

    if extra:
        cmd.extend(extra)

    if movflags:
        cmd.extend(_movflags_args(output_path))

    cmd.append(output_path)
    return cmd


def _sanitize_ffmpeg_number(value: Any, name: str) -> float:
    """Ensure a value is numeric and finite before FFmpeg interpolation. Returns float(value)."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise MCPVideoError(
            f"Invalid {name}: expected number, got {type(value).__name__}",
            error_type="validation_error",
            code="invalid_parameter",
        ) from None
    if not math.isfinite(result):
        raise MCPVideoError(
            f"Invalid {name}: must be a finite number, got {result}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return result


def _format_ffmpeg_number(value: Any) -> str:
    """Format a finite number for FFmpeg interpolation (integers stay bare).

    Single source of truth for the byte-identical formatter previously copied
    into the compositor modules (``_num`` / ``_fmt_num``). Fails closed on a
    non-finite / non-numeric value via ``_sanitize_ffmpeg_number``.
    """
    number = _sanitize_ffmpeg_number(value, "ffmpeg number")
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _escape_ffmpeg_filter_value(value: str) -> str:
    """Escape special characters for FFmpeg filter expressions (subtitles, drawtext, etc.)."""
    return (
        value.replace("\\", "\\\\")
        .replace("'", "'\\''")
        .replace(":", "\\:")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("=", "\\=")
    )


def _get_video_duration(video_path: str) -> float:
    """Get video duration using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = _run_command(cmd)
    stdout = result.stdout.strip()
    if not stdout:
        raise ProcessingError(" ".join(cmd), result.returncode, result.stderr)
    try:
        return float(stdout)
    except ValueError:
        raise ProcessingError(
            " ".join(cmd), result.returncode, f"Non-numeric duration from ffprobe: {stdout!r}"
        ) from None


def _run_ffprobe_json(path: str) -> dict[str, Any]:
    """Run ffprobe returning full JSON (format + streams)."""
    import json as _json

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = _run_command(cmd, timeout=FFPROBE_TIMEOUT)
    try:
        return _json.loads(result.stdout)
    except _json.JSONDecodeError as e:
        raise ProcessingError(" ".join(cmd), result.returncode, f"Invalid JSON from ffprobe: {e}") from None


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format HH:MM:SS,mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
