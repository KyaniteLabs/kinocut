"""Public validation adapter: Pydantic errors → stable contract errors.

Model validators may raise Pydantic's ``ValidationError`` (carrying rich custom
errors) internally, but *public* APIs — anything a store, CLI, or MCP surface
calls — must present one uniform, privacy-safe shape. These adapters catch
``ValidationError`` at the write/read boundary and re-raise a stable
:class:`MCPVideoError`: ``unknown_record_field`` when the failure is an
unexpected field, ``invalid_record`` otherwise. No raw ``ValueError`` or input
value ever escapes.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from kinocut.contracts._errors import (
    INVALID_RECORD,
    UNKNOWN_RECORD_FIELD,
    contract_error,
)

# Works for any strict model — canonical records and embedded value objects alike.
_M = TypeVar("_M", bound=BaseModel)


def _code_for(exc: ValidationError) -> str:
    """Pick the stable contract code: unknown-field beats a generic invalid."""

    for error in exc.errors():
        if error.get("type") == "extra_forbidden":
            return UNKNOWN_RECORD_FIELD
    return INVALID_RECORD


def _summary(model_cls: type[BaseModel], exc: ValidationError) -> str:
    """A bounded, privacy-safe message — never echoes offending input values."""

    return f"{model_cls.__name__} failed validation ({exc.error_count()} error(s))"


def validate_record(model_cls: type[_M], data: Any) -> _M:
    """Construct ``model_cls`` from ``data``, mapping validation failure to a code."""

    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise contract_error(_summary(model_cls, exc), _code_for(exc)) from exc


def parse_record_json(model_cls: type[_M], text: str) -> _M:
    """Parse one canonical JSON record, mapping malformed/invalid input to a code."""

    try:
        return model_cls.model_validate_json(text)
    except ValidationError as exc:
        raise contract_error(_summary(model_cls, exc), _code_for(exc)) from exc


__all__ = ["parse_record_json", "validate_record"]
