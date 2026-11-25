"""Export operation wrapper for the FFmpeg engine."""

from __future__ import annotations

from collections.abc import Callable
import os
import tempfile

from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .models import EditResult, ExportFormat, QualityLevel
from .paths import _auto_output


def export_video(
    input_path: str,
    output_path: str | None = None,
    quality: QualityLevel = "high",
    format: ExportFormat = "mp4",
    on_progress: Callable[[float], None] | None = None,
    two_pass: bool = False,
    target_bitrate: int | None = None,
    c2pa_manifest_path: str | None = None,
    c2pa_tool_path: str | None = None,  # deprecated: ignored; c2patool resolved from env/config only
    c2pa_signer_path: str | None = None,
) -> EditResult:
    """Export a video for final delivery with quality tuning.

    This is a convenience wrapper around :func:`convert` that defaults to
    high-quality mp4.  Use it when you want to re-encode for publishing
    rather than change the format.
    """
    input_path = _validate_input_path(input_path)
    from .engine_convert import convert

    if c2pa_manifest_path is None:
        result = convert(
            input_path,
            format=format,
            quality=quality,
            output_path=output_path,
            on_progress=on_progress,
            two_pass=two_pass,
            target_bitrate=target_bitrate,
        )
        result.operation = "export"
        return result

    if format != "mp4":
        from .errors import MCPVideoError

        raise MCPVideoError(
            "C2PA signing is currently supported only for final mp4 exports",
            error_type="validation_error",
            code="c2pa_requires_mp4",
        )

    from .c2pa import preflight_c2pa, sign_export_with_c2pa

    # Validate offline policy, manifest, c2patool availability, and final
    # destination BEFORE rendering so signing failure never leaves an unsigned MP4.
    preflight_c2pa(c2pa_manifest_path)
    final_output = output_path or _auto_output(input_path, format, ext=".mp4")
    _validate_output_path(final_output)

    with tempfile.TemporaryDirectory(prefix="kinocut-c2pa-export-") as stage_dir:
        staged_unsigned = os.path.join(stage_dir, "unsigned.mp4")
        result = convert(
            input_path,
            format=format,
            quality=quality,
            output_path=staged_unsigned,
            on_progress=on_progress,
            two_pass=two_pass,
            target_bitrate=target_bitrate,
        )
        result.operation = "export"
        if os.path.realpath(result.output_path) == os.path.realpath(staged_unsigned):
            result.c2pa = sign_export_with_c2pa(
                staged_unsigned,
                manifest_path=c2pa_manifest_path,
                signer_path=c2pa_signer_path,
                output_path=final_output,
            )
            result.output_path = final_output
            if os.path.isfile(final_output):
                result.size_mb = round(os.path.getsize(final_output) / (1024 * 1024), 2)
        else:
            # Compatibility with monkeypatched convert() stubs in unit tests.
            result.c2pa = sign_export_with_c2pa(
                result.output_path,
                manifest_path=c2pa_manifest_path,
                signer_path=c2pa_signer_path,
            )
    return result
