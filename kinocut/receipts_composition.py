"""Composition-provenance fields for the Video Receipt.

``composition_source`` records how a receipt's visual composition was sourced:
``live-html`` when it derives from live application HTML (a native Hyperframes
project or a ``hyperframes-capture`` ingest of a live URL), ``capture`` when it
derives from captured or generated media files (screenshots, screen recordings,
footage clips, synthetic fixtures). A ``capture`` composition always yields a
warning-class finding so screenshot-sourced work stays mechanically visible;
the warning never blocks a pipeline by itself. A missing or unknown
``composition_source`` is a schema error.
"""

from __future__ import annotations

from typing import Any

COMPOSITION_SOURCE_LIVE_HTML = "live-html"
COMPOSITION_SOURCE_CAPTURE = "capture"
COMPOSITION_SOURCE_VALUES = (COMPOSITION_SOURCE_LIVE_HTML, COMPOSITION_SOURCE_CAPTURE)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


def composition_source_findings(receipt: Any) -> list[dict[str, str]]:
    """Validate composition provenance on a Video Receipt.

    Returns a list of findings, each with ``severity`` (``error`` or
    ``warning``), ``code``, and ``message``. ``error`` findings mark a
    schema-invalid receipt; ``warning`` findings are the visible capture
    flag. An empty list means a clean ``live-html`` receipt.
    """
    findings: list[dict[str, str]] = []
    if not isinstance(receipt, dict):
        return [
            {
                "severity": SEVERITY_ERROR,
                "code": "composition_source_invalid_receipt",
                "message": "video receipt must be a mapping",
            }
        ]
    source = receipt.get("composition_source")
    if not isinstance(source, str) or not source:
        findings.append(
            {
                "severity": SEVERITY_ERROR,
                "code": "composition_source_required",
                "message": "video receipt is missing required composition_source (live-html|capture)",
            }
        )
        return findings
    if source not in COMPOSITION_SOURCE_VALUES:
        valid = "|".join(COMPOSITION_SOURCE_VALUES)
        findings.append(
            {
                "severity": SEVERITY_ERROR,
                "code": "composition_source_invalid",
                "message": f"composition_source must be one of {valid}, got {source!r}",
            }
        )
        return findings
    detail = receipt.get("composition_source_detail")
    if detail is not None and (not isinstance(detail, str) or not detail.strip()):
        findings.append(
            {
                "severity": SEVERITY_ERROR,
                "code": "composition_source_detail_invalid",
                "message": "composition_source_detail must be a non-empty string when present",
            }
        )
    if source == COMPOSITION_SOURCE_CAPTURE:
        findings.append(
            {
                "severity": SEVERITY_WARNING,
                "code": "composition_source_capture",
                "message": (
                    "composition derives from captured/generated media rather than live "
                    "application HTML; verify against the no-screenshot law before publishing"
                ),
            }
        )
    return findings
