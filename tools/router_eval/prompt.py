"""Prompt construction for the d1-2B treatment arm.

The prompt is part of the pre-registered protocol: changing any literal here
changes the template fingerprint and must be recorded in the manifest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from .catalog import Operation

TEMPLATE_VERSION = "router-eval-v1"
INSTRUCTIONS = "Pick the kinocut operation that should handle this request, or unsure if none clearly fits."
UNSURE = "None of the candidates clearly handles this request."
STATE_FORMAT = "User request: {request}\nContext: {context}"

_TEMPLATE_SPEC = {
    "version": TEMPLATE_VERSION,
    "state": STATE_FORMAT,
    "question_type": "choice",
    "instructions": INSTRUCTIONS,
    "unsure": UNSURE,
    "candidate_source": "r2_top5",
    "criteria_source": "operation_summary_first_line",
}


def build_state(request: str, context: object | None) -> str:
    """Render the protocol's state string (``none`` when no context exists)."""

    if context is None:
        rendered = "none"
    elif isinstance(context, str):
        rendered = context
    else:
        rendered = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return STATE_FORMAT.format(request=request, context=rendered)


def build_criteria(
    candidates: Sequence[str],
    operations: Mapping[str, Operation],
) -> dict[str, str]:
    """Return the closed choice criteria for one question."""

    if not candidates:
        raise ValueError("at least one candidate is required")
    criteria = {name: operations[name].summary or name for name in candidates}
    criteria["unsure"] = UNSURE
    return criteria


def build_question(
    candidates: Sequence[str],
    operations: Mapping[str, Operation],
) -> dict[str, object]:
    """Return the one choice question the treatment arm asks."""

    return {
        "type": "choice",
        "instructions": INSTRUCTIONS,
        "criteria": build_criteria(candidates, operations),
    }


def build_body(
    *,
    model: str,
    request: str,
    context: object | None,
    candidates: Sequence[str],
    operations: Mapping[str, Operation],
) -> dict[str, object]:
    """Return the complete POST body sent to ``/v1/systemone``."""

    return {
        "model": model,
        "state": build_state(request, context),
        "questions": {"operation": build_question(candidates, operations)},
    }


def template_fingerprint() -> str:
    """Return the sha256 of the canonical prompt specification."""

    canonical = json.dumps(_TEMPLATE_SPEC, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
