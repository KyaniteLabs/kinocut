"""Strict public-input validation helpers for subtitle QA."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping

from pydantic import ValidationError

from kinocut.contracts._common import (
    NormalizedRegion,
    _CREATED_BY_PATTERN,
    _SHA256_PATTERN,
)
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_RESOLUTION

_ERR_CODE = "invalid_subtitle_qa_input"


def qa_error(message: str) -> MCPVideoError:
    """Build the stable typed validation error for subtitle QA."""

    return MCPVideoError(message, error_type="validation_error", code=_ERR_CODE)


def validate_project_id(project_id: object) -> None:
    """Require a non-empty project identifier."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise qa_error("project_id must be a non-empty string")


def validate_created_by(created_by: object) -> None:
    """Require the canonical bounded actor grammar before creating findings."""

    if not isinstance(created_by, str) or re.fullmatch(_CREATED_BY_PATTERN, created_by) is None:
        raise qa_error("created_by must identify a human, agent, or tool actor")


def validate_target_id(target_id: object) -> None:
    """Require a complete lowercase SHA-256 asset identifier."""

    if not isinstance(target_id, str) or re.fullmatch(_SHA256_PATTERN, target_id) is None:
        raise qa_error("target_id must be a complete sha256 asset id")


def validate_threshold(value: object, name: str, *, allow_zero: bool = False) -> float:
    """Require a finite positive QA threshold; gap may explicitly be zero."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise qa_error(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise qa_error(f"{name} must be a finite number")
    if number < 0.0 or (number == 0.0 and not allow_zero):
        raise qa_error(f"{name} is outside its allowed range")
    return number


def normalized_overlay(region: Mapping[str, object]) -> NormalizedRegion:
    """Parse one strict normalized rectangle and wrap model errors."""

    try:
        return NormalizedRegion.model_validate(dict(region))
    except (ValidationError, TypeError, ValueError):
        raise qa_error("overlay region must be a normalized rectangle") from None


def validate_safe_area_profile(profile: object) -> None:
    """Validate profile dimensions, geometry, font, and line limits."""

    positive_ints = (
        ("display_width", profile.display_width),
        ("display_height", profile.display_height),
        ("subtitle_font_size_px", profile.subtitle_font_size_px),
        ("max_chars_per_line", profile.max_chars_per_line),
        ("max_lines", profile.max_lines),
    )
    for name, value in positive_ints:
        if type(value) is not int or value < 1 or value > MAX_RESOLUTION:
            raise qa_error(f"{name} must be an integer between 1 and {MAX_RESOLUTION}")
    bounded = (
        ("title_safe_margin_pct", profile.title_safe_margin_pct, 0.0, 0.5, False),
        ("subtitle_anchor_x_pct", profile.subtitle_anchor_x_pct, 0.0, 1.0, True),
        ("subtitle_anchor_y_pct", profile.subtitle_anchor_y_pct, 0.0, 1.0, True),
    )
    for name, value, minimum, maximum, inclusive_max in bounded:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise qa_error(f"{name} must be a finite normalized number")
        number = float(value)
        beyond_max = number > maximum if inclusive_max else number >= maximum
        if not math.isfinite(number) or number < minimum or beyond_max:
            raise qa_error(f"{name} is outside its allowed range")
