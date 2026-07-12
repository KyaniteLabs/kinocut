"""Additive attach/read helpers for the ``ai_video`` receipt section (Task 5).

The ``ai_video`` section is *purely additive*: :func:`attach_ai_video_section`
returns a new receipt dict with a single nested ``ai_video`` key added and every
legacy top-level field left byte-identical — the caller's dict is never mutated.
:func:`read_ai_video_section` returns the typed section, ``None`` when absent, or
a stable :class:`~kinocut.errors.MCPVideoError` when the embedded section is
malformed (via the shared validation adapter).
"""

from __future__ import annotations

import copy
from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.receipt_ai_video import AiVideoReceiptSection

_AI_VIDEO_KEY = "ai_video"


def attach_ai_video_section(receipt: dict[str, Any], section: AiVideoReceiptSection) -> dict[str, Any]:
    """Return a copy of ``receipt`` with the additive ``ai_video`` section attached.

    The input dict is deep-copied, so no legacy field (nested or top-level) is
    ever mutated. Refuses to overwrite an existing ``ai_video`` key — attaching
    is a one-time additive operation, never a silent clobber.
    """

    if not isinstance(receipt, dict):
        raise contract_error("receipt must be a mapping", INVALID_RECORD)
    if not isinstance(section, AiVideoReceiptSection):
        raise contract_error("section must be an AiVideoReceiptSection", INVALID_RECORD)
    if _AI_VIDEO_KEY in receipt:
        raise contract_error("receipt already carries an ai_video section", INVALID_RECORD)
    merged = copy.deepcopy(receipt)
    merged[_AI_VIDEO_KEY] = section.model_dump(mode="json")
    return merged


def read_ai_video_section(receipt: dict[str, Any]) -> AiVideoReceiptSection | None:
    """Return the typed ``ai_video`` section, or ``None`` when it is absent.

    A present-but-malformed section surfaces as a stable ``MCPVideoError`` through
    the shared adapter (``unknown_record_field`` / ``invalid_record``).
    """

    raw = receipt.get(_AI_VIDEO_KEY)
    if raw is None:
        return None
    return validate_record(AiVideoReceiptSection, raw)
