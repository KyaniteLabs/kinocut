"""Export operation wrapper for the FFmpeg engine."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from typing import Any

from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .models import EditResult, ExportFormat, QualityLevel


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
    if c2pa_manifest_path is not None:
        if format != "mp4":
            raise MCPVideoError(
                "C2PA signing is currently supported only for final mp4 exports",
                error_type="validation_error",
                code="c2pa_requires_mp4",
            )
        from .c2pa import sign_export_with_c2pa

        result.c2pa = sign_export_with_c2pa(
            result.output_path,
            manifest_path=c2pa_manifest_path,
            signer_path=c2pa_signer_path,
        )
    return result


def export_reviewed_cut(
    input_path: str,
    output_path: str,
    *,
    quality: QualityLevel,
    c2pa_manifest_path: str | None,
    profile: str | None,
    profile_reason: str | None,
    override_reason: str | None,
) -> tuple[EditResult, dict[str, Any]]:
    """Check and export the same private copy, recording the approval decision."""
    from .quality_guardrails import assert_quality
    from .quality_profiles import resolve_quality_profile
    from .source_identity import assert_source_identity, stream_source_identity

    resolve_quality_profile(profile)
    _validate_output_path(output_path)
    identity = stream_source_identity(input_path)
    override_reason = (override_reason or "").strip()[:200] or None
    with tempfile.TemporaryDirectory(prefix="kinocut_review_export_") as work:
        snapshot = os.path.join(work, os.path.basename(input_path))
        shutil.copyfile(input_path, snapshot)
        assert_source_identity(snapshot, identity)
        try:
            report = assert_quality(snapshot, profile=profile, profile_reason=profile_reason, require_clean_audio=True)
        except MCPVideoError as exc:
            if exc.code != "quality_gate_failed" or override_reason is None:
                raise
            checkpoint = {"passed": False, "failure": exc.to_dict(), "override_reason": override_reason}
        else:
            report["video"] = input_path
            checkpoint = {"passed": True, "report": report}
        result = export_video(snapshot, output_path=output_path, quality=quality, c2pa_manifest_path=c2pa_manifest_path)
    return result, {"source_sha256": identity.asset_id, "checkpoint": checkpoint}
