"""Shared, explicit repurpose quality policy for synchronous and durable routes."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

from .defaults import DEFAULT_QUALITY_GATE_SCORE
from .errors import MCPVideoError
from .validation import MAX_QUALITY_GATE_SCORE, MIN_QUALITY_GATE_SCORE


def validate_quality_score(value: Any) -> float:
    """Retain numeric-string compatibility without admitting bool/NaN/overflow."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MCPVideoError(
            "min_score must be a finite score from 0 to 100", error_type="validation_error", code="invalid_parameter"
        )
    try:
        if isinstance(value, str):
            value = float(value)
        if not MIN_QUALITY_GATE_SCORE <= value <= MAX_QUALITY_GATE_SCORE:
            raise ArithmeticError
        score = float(value)
        if not math.isfinite(score):
            raise ArithmeticError
    except (ValueError, OverflowError, ArithmeticError):
        raise MCPVideoError(
            "min_score must be a finite score from 0 to 100", error_type="validation_error", code="invalid_parameter"
        ) from None
    return score


class RepurposeReleasePolicy(BaseModel):
    """Frozen score/checkpoint policy; opt-out is explicit, never inferred."""

    model_config = ConfigDict(extra="forbid")
    include_release_checkpoint: StrictBool = True
    min_score: float = DEFAULT_QUALITY_GATE_SCORE

    @field_validator("min_score", mode="before")
    @classmethod
    def _score(cls, value: Any) -> float:
        return validate_quality_score(value)


def repurpose_release_policy(include_release_checkpoint: Any, min_score: Any) -> RepurposeReleasePolicy:
    """Validate public options before any media processing or job creation."""
    if type(include_release_checkpoint) is not bool:
        raise MCPVideoError(
            "include_release_checkpoint must be a boolean", error_type="validation_error", code="invalid_parameter"
        )
    return RepurposeReleasePolicy(include_release_checkpoint=include_release_checkpoint, min_score=min_score)
