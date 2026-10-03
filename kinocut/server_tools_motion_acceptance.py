"""MCP parity for explicit source/report-bound human motion attestation."""

from __future__ import annotations

from typing import Any, Literal

from .server_app import _result, _safe_tool, mcp


@mcp.tool()
@_safe_tool
def video_record_motion_acceptance(
    report: dict[str, Any],
    input_path: str,
    reviewer_id: str,
    source_sha256: str,
    report_sha256: str,
    watched_intervals: list[dict[str, Any]],
    dispositions: dict[str, str],
    verdict: Literal["accept", "reject"],
) -> dict[str, Any]:
    """Record an authorized human caller's explicit whole-film motion attestation.

    The caller must provide the exact source/report hashes, complete watched
    intervals and every flagged interval's disposition. Requires explicit human
    review; agents must not invent viewing or act as the reviewer. This records
    an unverified caller attestation, not model proof or release approval. No
    system-authenticated viewing evidence exists: attestation_verified_by_system
    remains false. The returned receipt is nested to preserve its content hash.
    """
    from .aivideo.inspection.motion_acceptance import record_motion_acceptance

    receipt = record_motion_acceptance(
        report,
        input_path=input_path,
        reviewer_id=reviewer_id,
        source_sha256=source_sha256,
        report_sha256=report_sha256,
        watched_intervals=watched_intervals,
        dispositions=dispositions,
        verdict=verdict,
    )
    return _result({"receipt": receipt})
