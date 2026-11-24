"""Stage and validate the ASS source shared by subtitle burn-in and Shorts."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .defaults import DEFAULT_SUBTITLE_STYLE
from .engine_probe import probe
from .engine_runtime_utils import _require_filter
from .errors import MCPVideoError
from .ffmpeg_helpers import (
    _escape_ffmpeg_filter_path,
    _escape_ffmpeg_filter_value,
    _run_ffmpeg,
    _validate_input_path,
)
from .validation import SUBTITLE_STYLE_KEYS, SUBTITLE_STYLE_VALUE_RE

_SUBTITLE_FORMATS = {"ass", "srt", "vtt"}

_PLAYRES_LINE = re.compile(r"(?i)^\s*PlayRes[XY]\s*:")
_SCRIPT_INFO_HEADER = re.compile(r"(?i)^\s*\[Script Info\]\s*$")
_ASS_DIALOGUE_LINE = re.compile(r"(?i)^\s*Dialogue\s*:\s*(.*)$")


def _has_renderable_ass_dialogue(content: str) -> bool:
    for line in content.splitlines():
        match = _ASS_DIALOGUE_LINE.match(line)
        if not match:
            continue
        # ASS Dialogue has nine metadata fields followed by the event text.
        # A prefix alone or an event with an empty text field cannot draw a cue.
        fields = match.group(1).split(",", 9)
        if len(fields) == 10 and fields[9].strip():
            return True
    return False


def _require_renderable_ass_dialogue(content: str) -> None:
    """Reject an ASS document that cannot render any caption event."""

    if not _has_renderable_ass_dialogue(content):
        raise MCPVideoError(
            "subtitle file contains no renderable cues",
            error_type="validation_error",
            code="subtitle_no_cues",
        )


def _style_error() -> MCPVideoError:
    # Never echo the raw hostile value — only the closed, safe key list.
    return MCPVideoError(
        "invalid subtitle style; expected comma-separated Key=Value pairs from the allowed style keys with safe values",
        error_type="validation_error",
        code="invalid_subtitle_style",
    )


def _subtitle_format(subtitle_path: str, *, format_hint: str | None = None) -> str:
    """Return ``ass`` | ``srt`` | ``vtt`` for a subtitle path; reject anything else."""

    subtitle_format = os.path.splitext(subtitle_path)[1][1:].lower() if format_hint is None else format_hint
    if subtitle_format in _SUBTITLE_FORMATS:
        return subtitle_format
    raise MCPVideoError(
        "unsupported subtitle format; expected a .srt, .vtt, or .ass file",
        error_type="validation_error",
        code="unsupported_subtitle_format",
    )


def parse_force_style(style: str) -> str:
    """Validate a user ``force_style`` string via a closed key parser.

    Returns a safe ``Key=Value,Key=Value`` string (embeddable inside
    ``force_style='...'``) or raises ``invalid_subtitle_style`` without echoing the
    offending value.
    """

    if not isinstance(style, str) or not style.strip():
        raise _style_error()
    # Reject control characters up front — .strip()/`$` would otherwise swallow a
    # trailing newline and make a hostile value look benign.
    if any(ord(char) < 0x20 for char in style):
        raise _style_error()
    pairs: list[str] = []
    for chunk in style.split(","):
        key, sep, value = chunk.partition("=")
        key = key.strip()
        value = value.strip()
        if not sep or not key or not value:
            raise _style_error()
        if key.lower() not in SUBTITLE_STYLE_KEYS:
            raise _style_error()
        if not SUBTITLE_STYLE_VALUE_RE.fullmatch(value):
            raise _style_error()
        # Defense in depth: FFmpeg-escape every validated value before it is
        # embedded in the subtitles filter's force_style option.
        pairs.append(f"{key}={_escape_ffmpeg_filter_value(value)}")
    if not pairs:
        raise _style_error()
    return ",".join(pairs)


def probe_display_dimensions(input_path: str) -> tuple[int, int]:
    """Return the rotation-normalized ``(width, height)`` a viewer actually sees."""

    info = probe(input_path)
    width, height = int(info.width), int(info.height)
    if abs(int(info.rotation)) % 180 == 90:
        width, height = height, width
    if width <= 0 or height <= 0:
        raise MCPVideoError(
            "could not determine display dimensions for subtitle rendering",
            error_type="validation_error",
            code="no_video_stream",
        )
    return width, height


def _normalize_playres(ass_content: str, width: int, height: int) -> str:
    """Strip every existing PlayResX/Y and insert exactly one pair = ``(width, height)``."""

    kept = [line for line in ass_content.splitlines() if not _PLAYRES_LINE.match(line)]
    result: list[str] = []
    inserted = False
    for line in kept:
        result.append(line)
        if not inserted and _SCRIPT_INFO_HEADER.match(line):
            result.append(f"PlayResX: {width}")
            result.append(f"PlayResY: {height}")
            inserted = True
    if not inserted:
        result = ["[Script Info]", f"PlayResX: {width}", f"PlayResY: {height}", *result]
    return "\n".join(result) + "\n"


def filter_safe_ass_workdir(*preferred_dirs: str) -> str:
    """Select an apostrophe-free existing staging directory lazily, or fail closed."""
    for candidate in preferred_dirs:
        if "'" not in candidate and os.path.isdir(candidate):
            return candidate
    for resolver in (tempfile.gettempdir, os.getcwd):
        try:
            candidate = resolver()
        except OSError:
            continue
        if "'" not in candidate and os.path.isdir(candidate):
            return candidate
    raise _prepare_error()


def _prepare_error() -> MCPVideoError:
    return MCPVideoError(
        "failed to prepare the subtitle file for burn-in",
        error_type="processing_error",
        code="subtitle_prepare_failed",
    )


def subtitle_burn_workdir(output_path: str) -> str:
    return filter_safe_ass_workdir(os.path.dirname(os.path.abspath(output_path)))


@dataclass(frozen=True)
class StagedBurnSource:
    path: str
    video_filter: str
    original_path: str

    def advisory(self, media: str, *, profile: str | None = None) -> dict[str, Any]:
        from .aivideo.subtitle_advisory import subtitle_advisory

        return subtitle_advisory(media, self.original_path, profile=profile, burn_ass=self.path)


def _copy_authored_ass(source: str, fd: int) -> None:
    try:
        with os.fdopen(fd, "wb") as dst:
            fd = -1
            with open(source, "rb") as src:
                if not any(_has_renderable_ass_dialogue(line.decode("utf-8", errors="replace")) for line in src):
                    _require_renderable_ass_dialogue("")
                src.seek(0)
                shutil.copyfileobj(src, dst)
    finally:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)


def _convert_to_dimensioned_ass(
    source: str,
    fd: int,
    subtitle_format: str,
    display_size: tuple[int, int],
    workdir: str,
) -> None:
    input_format = "webvtt" if subtitle_format == "vtt" else "srt"
    try:
        with tempfile.TemporaryDirectory(prefix="kc_ass_", dir=workdir) as private_dir:
            converted = os.path.join(private_dir, "converted.ass")
            _run_ffmpeg(["-y", "-f", input_format, "-i", source, converted])
            normalized = _normalize_playres(
                Path(converted).read_text(encoding="utf-8", errors="replace"), *display_size
            )
        _require_renderable_ass_dialogue(normalized)
        with os.fdopen(fd, "w", encoding="utf-8") as dst:
            fd = -1
            dst.write(normalized)
    finally:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)


@contextlib.contextmanager
def staged_burn_source(
    subtitle_path: str,
    input_path: str,
    output_path: str,
    *,
    style: str | None = None,
    display_size: tuple[int, int] | None = None,
    format_hint: str | None = None,
    workdir_for: Callable[[str], str] = subtitle_burn_workdir,
) -> Iterator[StagedBurnSource]:
    """Keep a filter-safe ASS and its filter available through render and advisory QA."""
    source = _validate_input_path(subtitle_path)
    subtitle_format = _subtitle_format(source, format_hint=format_hint)
    _require_filter("subtitles", "Subtitle burn-in")
    if style is None and subtitle_format != "ass":
        style = DEFAULT_SUBTITLE_STYLE
    force_style = parse_force_style(style) if style is not None else None

    path = None
    fd = -1
    try:
        try:
            workdir = workdir_for(output_path)
            fd, path = tempfile.mkstemp(suffix=".ass", dir=workdir)
            if subtitle_format == "ass":
                owned, fd = fd, -1
                _copy_authored_ass(source, owned)
            else:
                size = display_size if display_size is not None else probe_display_dimensions(input_path)
                owned, fd = fd, -1
                _convert_to_dimensioned_ass(source, owned, subtitle_format, size, workdir)
            video_filter = f"subtitles={_escape_ffmpeg_filter_path(path)}"
            if force_style is not None:
                video_filter += f":force_style='{force_style}'"
        except OSError as exc:
            raise _prepare_error() from exc
        finally:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
        yield StagedBurnSource(path, video_filter, source)
    finally:
        if path is not None:
            with contextlib.suppress(OSError):
                os.unlink(path)
