"""Shared FFmpeg helper functions.

Centralises duplicated utilities used across engine modules so there is a
single authoritative copy of each helper.
"""

from __future__ import annotations

import contextlib
import math
import os
import re
import subprocess
from collections.abc import Callable
from typing import Any, BinaryIO

from .errors import InputFileError, MCPVideoError, ProcessingError, parse_ffmpeg_error
from .limits import (
    DEFAULT_FFMPEG_TIMEOUT,
    FFMPEG_STDERR_DIAGNOSTIC_BYTES,
    FFPROBE_TIMEOUT,
    MAX_FILE_SIZE_MB,
    MAX_SUBPROCESS_STDOUT_BYTES,
    MAX_FFMPEG_PIPE_BYTES,
)
from . import publication
from .offline import is_offline_mode
from .publication import _staging, note_operation_write as _note_operation_write, record_operation_input
from .publication._operation import _reject_self_overwrite as _reject_self_overwrite
from .publication._policy import _validate_write_path as _validate_write_path
from .validation_errors import exception_kind, rejected_value

_atomic_artifact = publication.atomic_artifact
_atomic_output = publication.atomic_output
_open_staged_writer = publication.open_staged_writer
_owns_operation_output = publication.owns_operation_output
_reset_operation_inputs = publication.reset_operation_inputs
_validate_artifact_location = publication.validate_artifact_location
_validate_artifact_path = publication.validate_artifact_path
_validate_output_path = publication.validate_output_path


def _offline_media_command(cmd: list[str], *, probe: bool = False) -> list[str]:
    """Apply FFmpeg's per-input protocol policy, including nested demuxer I/O."""
    if not is_offline_mode() or len(cmd) < 2 or cmd[1:] == ["-version"]:
        return cmd
    policy = ("-protocol_whitelist", "file,pipe")
    restricted = [cmd[0]]
    args = iter(cmd[1:])
    for arg in args:
        if arg == "-protocol_whitelist":
            next(args)
            restricted.extend(policy)
        elif not probe and arg == "-i":
            restricted.extend((*policy, arg, next(args)))
        else:
            restricted.append(arg)
    if probe:
        restricted[1:1] = policy
    elif "-i" in restricted:
        restricted[-1:-1] = policy
    return restricted


def _validate_input_path(path: str, *, record_operation: bool = True) -> str:
    """Resolve an existing input and reject null bytes or oversized files.

    Explicit in-place finalization may omit new input registration; previously
    registered inputs still remain protected by the write-path guard.
    """
    if "\x00" in path:
        raise InputFileError(path, "Path contains null bytes")
    resolved = os.path.realpath(path)
    if not os.path.isfile(resolved):
        raise InputFileError(resolved)
    try:
        size_mb = os.path.getsize(resolved) / (1024 * 1024)
    except OSError as e:
        raise InputFileError(resolved, f"Cannot read file size: {exception_kind(e)}") from None
    if size_mb > MAX_FILE_SIZE_MB:
        raise InputFileError(
            resolved,
            f"File size ({size_mb:.1f} MB) exceeds maximum of {MAX_FILE_SIZE_MB} MB",
        )
    if record_operation:
        record_operation_input(resolved)
    return resolved


def _validate_project_path(path: str) -> str:
    """Validate a project directory path."""
    if "\x00" in path:
        raise InputFileError(path, "Path contains null bytes")
    resolved = os.path.realpath(path)
    if not os.path.isdir(resolved):
        raise InputFileError(resolved, "Directory does not exist")
    return resolved


def _validate_artifact_input_path(path: str) -> str:
    """Read a saved artifact without granting permission to overwrite it."""
    _validate_artifact_location(path, "Artifact path")
    return _validate_input_path(path, record_operation=False)


def _run_command(
    cmd: list[str],
    timeout: int = DEFAULT_FFMPEG_TIMEOUT,
    *,
    pass_fds: tuple[int, ...] = (),
    stderr_sink: BinaryIO | None = None,
    stdout_sink: BinaryIO | None = None,
    stdout_limit: int = MAX_SUBPROCESS_STDOUT_BYTES,
) -> subprocess.CompletedProcess[str]:
    """Run an arbitrary command with timeout and error handling.

    Bare ``ffmpeg``/``ffprobe`` names are replaced with the resolved runtime
    binaries so every code path finds FFmpeg the same way. Optional ``stderr_sink``
    must be a seekable binary file. Pipes are drained with hard byte ceilings;
    oversized payloads fail without truncated success. Optional ``stdout_sink``
    receives at most ``stdout_limit`` bytes and returns ``result.stdout=None``.
    Failed commands read a bounded diagnostic prefix; successful sink callers
    inspect the sink themselves (``result.stderr`` is then ``None``).
    """
    from .engine_runtime_utils import _ffmpeg, _ffprobe
    from .bounded_process import run_bounded

    name = os.path.basename(cmd[0]).lower() if cmd else ""
    is_ffmpeg = name in {"ffmpeg", "ffmpeg.exe"}
    is_ffprobe = name in {"ffprobe", "ffprobe.exe"}
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
    output = cmd[-1] if cmd else ""
    staged = bool(cmd and _staging.is_staged_output(output))
    if staged and not is_ffmpeg and not is_ffprobe:
        from .errors import FFmpegNotFoundError

        try:
            is_ffmpeg = cmd[0] == _ffmpeg()
        except FFmpegNotFoundError:
            is_ffmpeg = False
    if is_ffmpeg or is_ffprobe:
        cmd = _offline_media_command(cmd, probe=is_ffprobe)
    cmd_str = " ".join(cmd)
    try:
        with contextlib.ExitStack() as lease:
            if is_ffmpeg:
                cmd, pass_fds = lease.enter_context(_staging.staged_ffmpeg_command(cmd, pass_fds))
            result = run_bounded(
                cmd,
                timeout=timeout,
                pass_fds=pass_fds,
                stderr_sink=stderr_sink,
                stdout_sink=stdout_sink,
                stdout_limit=stdout_limit,
            )
            if result.returncode != 0:
                if stderr_sink is not None:
                    stderr_sink.seek(0, os.SEEK_END)
                    stderr_sink.seek(max(0, stderr_sink.tell() - FFMPEG_STDERR_DIAGNOSTIC_BYTES))
                    result.stderr = stderr_sink.read(FFMPEG_STDERR_DIAGNOSTIC_BYTES).decode("utf-8", errors="replace")
                    stderr_sink.seek(0)
                raise ProcessingError(cmd_str, result.returncode, result.stderr)
    except subprocess.TimeoutExpired:
        raise ProcessingError(cmd_str, -1, "", reason=f"FFmpeg command timed out after {timeout}s") from None
    if is_ffmpeg and not staged and output != "-" and not output.startswith("pipe:") and os.path.isfile(output):
        _note_operation_write(output)
    return result


def _run_ffmpeg(
    args: list[str], *, pass_fds: tuple[int, ...] = (), timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg with raw args (resolved binary and ``-y`` are prepended)."""
    from .engine_runtime_utils import _ffmpeg
    from .limits import resolve_ffmpeg_timeout

    if args and args[0] in {"ffmpeg", "ffprobe"}:
        raise ValueError("_run_ffmpeg takes raw FFmpeg arguments; use _run_command for full command lists")
    effective_timeout = resolve_ffmpeg_timeout(timeout, default=DEFAULT_FFMPEG_TIMEOUT)
    cmd = _offline_media_command([_ffmpeg(), "-y", *args])

    try:
        with _staging.staged_ffmpeg_command(cmd, pass_fds) as (cmd, pass_fds):
            from .bounded_process import run_bounded

            proc = run_bounded(cmd, timeout=effective_timeout, pass_fds=pass_fds)
            if proc.returncode != 0:
                raise parse_ffmpeg_error(proc.stderr, command=cmd)
    except subprocess.TimeoutExpired as e:
        raise ProcessingError(
            " ".join(cmd), -1, "", reason=f"FFmpeg command timed out after {effective_timeout}s"
        ) from e
    if args and not _staging.is_staged_output(args[-1]) and os.path.isfile(args[-1]):
        _note_operation_write(args[-1])
    return proc


def _run_ffmpeg_bytes(args: list[str]) -> bytes:
    """Run FFmpeg with a binary ``pipe:1`` output and return its bytes.

    Derived artifact encoders use this no-path sink so FFmpeg never opens an
    output filename and therefore cannot follow a planted or swap-time symlink.
    Callers must include an explicit pipe muxer/codec and ``pipe:1`` output.
    """

    from .engine_runtime_utils import _ffmpeg
    from .limits import resolve_ffmpeg_timeout

    if not args or args[-1] != "pipe:1":
        raise MCPVideoError(
            "binary FFmpeg output must target pipe:1",
            error_type="validation_error",
            code="invalid_ffmpeg_pipe",
        )
    cmd = _offline_media_command([_ffmpeg(), "-y", *args])
    effective_timeout = resolve_ffmpeg_timeout(default=DEFAULT_FFMPEG_TIMEOUT)
    try:
        from .bounded_process import run_bounded

        proc = run_bounded(cmd, timeout=effective_timeout, text=False, stdout_limit=MAX_FFMPEG_PIPE_BYTES)
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(
            " ".join(cmd),
            -1,
            "",
            reason=f"FFmpeg command timed out after {effective_timeout}s",
        ) from exc
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise parse_ffmpeg_error(stderr, command=cmd)
    return proc.stdout


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

    from .ffmpeg_progress import run_progress

    command = _offline_media_command([_ffmpeg(), "-y", *args])
    with _staging.staged_ffmpeg_command(command) as (cmd, pass_fds):
        result = run_progress(
            cmd,
            estimated_duration,
            on_progress,
            _parse_ffmpeg_time,
            pass_fds=pass_fds,
            default_timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
    if args and not _staging.is_staged_output(args[-1]) and os.path.isfile(args[-1]):
        _note_operation_write(args[-1])
    return result


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
    if isinstance(value, bool):
        raise MCPVideoError(f"{name} must be numeric", error_type="validation_error", code="invalid_parameter")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise MCPVideoError(
            f"Invalid {name}: expected number, got {rejected_value(value)}",
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
    """Escape special characters for FFmpeg filter expressions (subtitles, drawtext, etc.).

    This applies a single escaping pass, which is correct for values that reach the
    filter already quoted (``lut3d=file='...'``) and for scalars such as numbers,
    colours and font *names*. Unquoted filesystem paths need
    ``_escape_ffmpeg_filter_path`` instead — see the note there.
    """
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


_WINDOWS_FILTER_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]{1,2}|\\\\)")


def _escape_ffmpeg_filter_path(value: str) -> str:
    """Escape a filesystem path used as an FFmpeg filter option value.

    Two shapes, two strategies — both verified against a real ``subtitles=``
    burn-in (ffmpeg 7.x, 2026-08-31), because every rule here was learned from
    an actual decoder failure, not from the docs:

    **Windows-style paths** (drive-letter or UNC prefix) stay *unquoted* with
    double-escaped colons and forward-slashed separators: ``C:\\dir\\subs.ass``
    becomes ``C\\\\:/dir/subs.ass``. Unquoted is what the two-parser reality
    requires here — the drive-letter colon must survive BOTH the filtergraph
    parser and the filter's own option parser, and quoting does not protect a
    colon from the option parser.

    **POSIX-style paths** are emitted *quoted* with a single escaping pass:
    ``'/tmp/a\\ b,x.ass'``-style output produced by wrapping
    :func:`_escape_ffmpeg_filter_value` in single quotes. Empirically the
    quoted single-pass form is the only strategy that lets literal
    backslashes and the filtergraph metacharacters ``, ; [ ] =`` reach the
    filter intact; every doubled-backslash variant tested fails one parser
    or the other, and the pre-quote unquoted form corrupted legal POSIX
    filenames (``/tmp/a\\b.ass`` opened as ``/tmp/a/b.ass``) and passed
    ``, ; [ ]`` through raw, splitting the filtergraph.

    Known limitation (fails under every strategy, including all historical
    ones — not a regression): a filename containing an apostrophe cannot be
    passed through this seam; FFmpeg's two quote-processing layers eat it in
    every quoting/escaping combination we tested.
    """
    if _WINDOWS_FILTER_PATH_RE.match(value):
        return value.replace("\\", "/").replace(":", "\\\\:")
    return f"'{_escape_ffmpeg_filter_value(value)}'"


def _get_video_duration(video_path: str, *, pass_fds: tuple[int, ...] = ()) -> float:
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
    result = _run_command(cmd, pass_fds=pass_fds) if pass_fds else _run_command(cmd)
    stdout = result.stdout.strip()
    if not stdout:
        raise ProcessingError(" ".join(cmd), result.returncode, result.stderr)
    try:
        return float(stdout)
    except ValueError:
        raise ProcessingError(
            " ".join(cmd),
            result.returncode,
            stdout,
            reason="the duration probe did not return a number",
        ) from None


def _run_ffprobe_json(
    path: str,
    *,
    pass_fds: tuple[int, ...] = (),
    count_frames: bool = False,
    timeout: int | None = None,
) -> dict[str, Any]:
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
    ]
    if count_frames:
        cmd.append("-count_frames")
    cmd.append(path)
    effective_timeout = FFPROBE_TIMEOUT if timeout is None else timeout
    result = (
        _run_command(cmd, timeout=effective_timeout, pass_fds=pass_fds)
        if pass_fds
        else _run_command(cmd, timeout=effective_timeout)
    )
    try:
        return _json.loads(result.stdout)
    except _json.JSONDecodeError as e:
        raise ProcessingError(
            " ".join(cmd), result.returncode, "", reason=f"Invalid JSON from ffprobe: {exception_kind(e)}"
        ) from None


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format HH:MM:SS,mmm."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
