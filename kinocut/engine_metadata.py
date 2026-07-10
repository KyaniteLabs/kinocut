"""Metadata read/write operations for the FFmpeg engine."""

from __future__ import annotations

import os

from .engine_probe import probe
from .engine_runtime_utils import _build_edit_result, _movflags_args, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _run_ffprobe_json
from .models import EditResult, MetadataResult


def read_metadata(input_path: str) -> MetadataResult:
    """Read metadata tags from a video/audio file.

    Args:
        input_path: Path to the input file.
    """
    input_path = _validate_input_path(input_path)
    data = _run_ffprobe_json(input_path)

    # Extract tags from format
    fmt_tags = data.get("format", {}).get("tags", {})
    # Also check stream tags
    stream_tags: dict[str, str] = {}
    for stream in data.get("streams", []):
        for k, v in stream.get("tags", {}).items():
            if k not in stream_tags:
                stream_tags[k] = v

    all_tags = {**stream_tags, **fmt_tags}

    return MetadataResult(
        title=all_tags.pop("title", None),
        artist=all_tags.pop("artist", None),
        album=all_tags.pop("album", None),
        comment=all_tags.pop("comment", None),
        date=all_tags.pop("date", None) or all_tags.pop("creation_time", None),
        tags=all_tags,
    )


def write_metadata(
    input_path: str,
    metadata: dict[str, str],
    output_path: str | None = None,
) -> EditResult:
    """Write metadata tags to a video/audio file.

    Args:
        input_path: Path to the input file.
        metadata: Dict of tag key-value pairs (e.g. {"title": "My Video", "artist": "Me"}).
        output_path: Where to save the output. If None, overwrites in place with a temp file.
    """
    input_path = _validate_input_path(input_path)
    if not metadata:
        raise MCPVideoError(
            "No metadata provided",
            error_type="validation_error",
            code="empty_metadata",
        )

    # Validate metadata keys and values: reject newlines, null bytes, and '=' in keys
    for key, value in metadata.items():
        if "=" in key or "\n" in key or "\0" in key:
            raise MCPVideoError(
                f"Invalid metadata key '{key}': keys cannot contain '=', newline, or null bytes",
                error_type="validation_error",
                code="invalid_metadata_key",
            )
        if "\n" in str(value) or "\0" in str(value):
            raise MCPVideoError(
                f"Invalid metadata value for '{key}': values cannot contain newline or null bytes",
                error_type="validation_error",
                code="invalid_metadata_value",
            )

    output = output_path or _auto_output(input_path, "tagged")
    _validate_output_path(output)

    if os.path.abspath(output) == os.path.abspath(input_path):
        raise MCPVideoError(
            "output_path cannot be the same as input_path for metadata writes. "
            "Use a different output path or omit it to auto-generate one.",
            error_type="validation_error",
            code="invalid_parameter",
        )

    args = ["-i", input_path]
    for key, value in metadata.items():
        args.extend(["-metadata", f"{key}={value}"])
    args.extend(["-c:v", "copy", "-c:a", "copy", *_movflags_args(output), output])

    with _timed_operation() as timing:
        _run_ffmpeg(args)

    return _build_edit_result(
        output,
        "write_metadata",
        timing,
        format=probe(output).format,
    )
