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
from collections.abc import Callable, Iterator
from contextvars import ContextVar
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
_SAFE_EXISTING_OUTPUT_SUFFIXES = frozenset(
    {
        ".aac",
        ".aif",
        ".aiff",
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
        ".ogg",
        ".opus",
        ".png",
        ".srt",
        ".ts",
        ".txt",
        ".vtt",
        ".wav",
        ".webm",
        ".webp",
    }
)


# Operation-scoped record of resolved input and written paths (self-overwrite guard).
#
# Every engine validates inputs through ``_validate_input_path`` and outputs
# through ``_validate_output_path``/``_validate_artifact_path``. Recording the
# inputs here lets the write guard reject an output that resolves to a path
# already read *in the same operation*, so ``output_path == input_path`` gets a
# structured guardrail error instead of silently destroying the source file.
#
# A ``ContextVar`` (not a module global) scopes the records safely: each MCP
# tool call runs as its own task or ``anyio.to_thread`` copy of the caller's
# context, so concurrent tool calls never see each other's paths, and nothing
# leaks between calls. Direct engine callers in one process share one scope —
# deliberately conservative (a write-back onto a previously read path is
# blocked there too).
#
# Written paths are tracked alongside inputs because engines probe their own
# render result after writing (``_build_edit_result`` → ``probe`` →
# ``_validate_input_path``). A path this operation has actually written is
# therefore *not* recorded as an input: re-rendering over an
# earlier output stays legal, while destroying a declared input stays blocked.
_OPERATION_INPUTS: ContextVar[frozenset[str]] = ContextVar("kinocut_operation_inputs", default=frozenset())
_OPERATION_WRITES: ContextVar[frozenset[str]] = ContextVar("kinocut_operation_writes", default=frozenset())


def _record_operation_input(resolved: str) -> None:
    """Record a validated input path for the current operation scope."""
    if resolved in _OPERATION_WRITES.get():
        return
    _OPERATION_INPUTS.set(_OPERATION_INPUTS.get() | {resolved})


def _note_operation_write(resolved: str) -> None:
    """Record an owned stage or successfully written artifact, never a precheck."""
    _OPERATION_WRITES.set(_OPERATION_WRITES.get() | {os.path.realpath(resolved)})


def _reset_operation_inputs() -> None:
    """Start a fresh operation scope for the self-overwrite guard.

    MCP tool calls never need this (context isolation scopes them already);
    long-running direct callers may use it between distinct operations.
    """
    _OPERATION_INPUTS.set(frozenset())
    _OPERATION_WRITES.set(frozenset())


def _reject_self_overwrite(path: str) -> None:
    """Reject a write whose target resolves to a path read as input this operation.

    Resolved-path compare (``realpath``) plus a ``samefile`` fallback for
    hardlinked spellings — the same shape as the provenance lanes' explicit
    ``_reject_output_alias`` guards, centralised for every media/artifact
    writer, and using their canonical message. Without it, a media-suffix
    output may legitimately overwrite an existing file, and when that file is
    also the operation's input, FFmpeg's ``-y`` silently destroys the source
    mid-render.
    """
    recorded = _OPERATION_INPUTS.get()
    if not recorded:
        return
    resolved_output = os.path.realpath(path)
    for input_path in recorded:
        if resolved_output == os.path.realpath(input_path):
            raise MCPVideoError(
                f"output path aliases an input of this operation: {path!r}",
                error_type="validation_error",
                code="invalid_output_path",
            )
    if not os.path.exists(path):
        return
    for input_path in recorded:
        try:
            if os.path.samefile(path, input_path):
                raise MCPVideoError(
                    f"output path aliases an input of this operation (same file): {path!r}",
                    error_type="validation_error",
                    code="invalid_output_path",
                )
        except OSError:
            # The realpath compare above already ran; an unreadable path here
            # cannot be proven identical, so fail open for the hardlink probe.
            continue


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
        raise InputFileError(resolved, f"Cannot read file size: {e}") from None
    if size_mb > MAX_FILE_SIZE_MB:
        raise InputFileError(
            resolved,
            f"File size ({size_mb:.1f} MB) exceeds maximum of {MAX_FILE_SIZE_MB} MB",
        )
    if record_operation:
        _record_operation_input(resolved)
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
    sensitive home dotfiles, and targets that resolve to a path already read
    as an input of the current operation (self-overwrite). When the target
    already exists, refuses to overwrite it unless its suffix is in
    ``allowed_existing_suffixes`` (media suffixes for renders; ``.json`` only
    for provenance artifacts).
    """
    if "\x00" in path:
        raise MCPVideoError(
            f"{label} contains null bytes: {path!r}",
            error_type="validation_error",
            code="invalid_output_path",
        )
    _reject_self_overwrite(path)
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

    Kinocut intentionally lets users write normal media artifacts around their
    projects and temp directories. It must not overwrite system files, symlink
    targets, sensitive home dotfiles, or obviously non-media source/config files.

    This is a prospective precheck. ``_atomic_output`` binds registered producer
    writes to an owned staging descriptor and anchors each file's publication.
    These protections do not provide a universal integrity guarantee against
    concurrent hostile writers in the destination directory.
    """
    return _validate_write_path(path, allowed_existing_suffixes=_SAFE_EXISTING_OUTPUT_SUFFIXES, label="Output path")


def _validate_artifact_path(path: str) -> str:
    """Validate a provenance-artifact write path (plan/receipt JSON).

    Same traversal / symlink / system-dir / sensitive-dotfile guard as
    ``_validate_output_path`` but stricter on overwrite: a workflow plan or
    receipt may only overwrite an existing ``.json`` artifact, never a media
    file or any other on-disk file.
    """
    return _validate_write_path(path, allowed_existing_suffixes=_SAFE_EXISTING_ARTIFACT_SUFFIXES, label="Artifact path")


@contextlib.contextmanager
def _atomic_output(path: str) -> Iterator[str]:
    """Stage and publish through an anchored output directory."""
    from .atomic_publication import anchored_output

    with anchored_output(path, _validate_output_path) as staged:
        yield staged


@contextlib.contextmanager
def _atomic_artifact(path: str) -> Iterator[str]:
    """Use the same anchored publication with the stricter JSON artifact guard."""
    from .atomic_publication import anchored_output

    with anchored_output(path, _validate_artifact_path) as staged:
        yield staged


def _open_staged_writer(path: str):
    """Return a binary writer bound to the transaction's original staging inode."""
    from .staged_writers import open_staged_writer

    return open_staged_writer(path)


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
    from .staged_writers import is_staged_output, staged_ffmpeg_command

    output = cmd[-1] if cmd else ""
    is_ffmpeg = bool(cmd and os.path.basename(cmd[0]).lower() in {"ffmpeg", "ffmpeg.exe"})
    if (
        cmd
        and is_staged_output(output)
        and not is_ffmpeg
        and os.path.basename(cmd[0]).lower() not in {"ffprobe", "ffprobe.exe"}
    ):
        from .errors import FFmpegNotFoundError

        try:
            is_ffmpeg = cmd[0] == _ffmpeg()
        except FFmpegNotFoundError:
            is_ffmpeg = False
    try:
        with contextlib.ExitStack() as lease:
            if is_ffmpeg:
                cmd, pass_fds = lease.enter_context(staged_ffmpeg_command(cmd, pass_fds))
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
                    stderr_sink.seek(0)
                    result.stderr = stderr_sink.read(FFMPEG_STDERR_DIAGNOSTIC_BYTES).decode("utf-8", errors="replace")
                    stderr_sink.seek(0)
                raise ProcessingError(cmd_str, result.returncode, result.stderr)
    except subprocess.TimeoutExpired:
        raise ProcessingError(cmd_str, -1, f"FFmpeg command timed out after {timeout}s") from None
    if is_ffmpeg and os.path.isfile(output):
        _note_operation_write(output)
    return result


def _run_ffmpeg(args: list[str], *, pass_fds: tuple[int, ...] = ()) -> subprocess.CompletedProcess[str]:
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
    from .staged_writers import staged_ffmpeg_command

    try:
        with staged_ffmpeg_command(cmd, pass_fds) as (cmd, pass_fds):
            from .bounded_process import run_bounded

            proc = run_bounded(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT, pass_fds=pass_fds)
            if proc.returncode != 0:
                raise parse_ffmpeg_error(proc.stderr, command=cmd)
    except subprocess.TimeoutExpired as e:
        raise ProcessingError(" ".join(cmd), -1, f"FFmpeg command timed out after {DEFAULT_FFMPEG_TIMEOUT}s") from e
    if args and os.path.isfile(args[-1]):
        _note_operation_write(args[-1])
    return proc


def _run_ffmpeg_bytes(args: list[str]) -> bytes:
    """Run FFmpeg with a binary ``pipe:1`` output and return its bytes.

    Derived artifact encoders use this no-path sink so FFmpeg never opens an
    output filename and therefore cannot follow a planted or swap-time symlink.
    Callers must include an explicit pipe muxer/codec and ``pipe:1`` output.
    """

    from .engine_runtime_utils import _ffmpeg

    if not args or args[-1] != "pipe:1":
        raise MCPVideoError(
            "binary FFmpeg output must target pipe:1",
            error_type="validation_error",
            code="invalid_ffmpeg_pipe",
        )
    cmd = [_ffmpeg(), "-y", *args]
    try:
        from .bounded_process import run_bounded

        proc = run_bounded(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT, text=False, stdout_limit=MAX_FFMPEG_PIPE_BYTES)
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(
            " ".join(cmd),
            -1,
            f"FFmpeg command timed out after {DEFAULT_FFMPEG_TIMEOUT}s",
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

    from .staged_writers import staged_ffmpeg_command

    with staged_ffmpeg_command([_ffmpeg(), "-y", *args]) as (cmd, pass_fds):
        result = run_progress(
            cmd,
            estimated_duration,
            on_progress,
            _parse_ffmpeg_time,
            pass_fds=pass_fds,
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
    if args and os.path.isfile(args[-1]):
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
            " ".join(cmd), result.returncode, f"Non-numeric duration from ffprobe: {stdout!r}"
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
        raise ProcessingError(" ".join(cmd), result.returncode, f"Invalid JSON from ffprobe: {e}") from None


def _seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format HH:MM:SS,mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
