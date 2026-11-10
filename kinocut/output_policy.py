"""Explicit overwrite consent and isolated ownership for a single tool call."""

from __future__ import annotations

import contextlib
import functools
import inspect
from contextvars import ContextVar
from typing import Annotated, Any

from pydantic import Field

from .defaults import DEFAULT_OVERWRITE
from .errors import MCPVideoError

_OVERWRITE: ContextVar[bool | None] = ContextVar("kinocut_overwrite", default=None)
_OVERWRITE_TYPE = Annotated[
    bool,
    Field(strict=True, description="Allow replacing existing media files."),
]


@contextlib.contextmanager
def output_operation(overwrite: bool = DEFAULT_OVERWRITE):
    """Scope consent and input/output ownership to this job, including worker threads."""
    if type(overwrite) is not bool:
        raise MCPVideoError(
            "overwrite must be an explicit boolean", error_type="validation_error", code="invalid_parameter"
        )
    from .ffmpeg_helpers import _OPERATION_INPUTS, _OPERATION_WRITES

    fresh = _OVERWRITE.get() is None
    consent = _OVERWRITE.set(overwrite)
    inputs = _OPERATION_INPUTS.set(frozenset()) if fresh else None
    writes = _OPERATION_WRITES.set({}) if fresh else None
    try:
        yield
    finally:
        if fresh:
            _OPERATION_INPUTS.reset(inputs)
            _OPERATION_WRITES.reset(writes)
        _OVERWRITE.reset(consent)


def with_output_policy(fn: Any) -> Any:
    """Expose a strict ``overwrite=false`` keyword on each MCP handler."""
    if getattr(fn, "_kinocut_output_policy", False):
        return fn
    original = inspect.unwrap(fn)
    signature = inspect.signature(fn, globals=original.__globals__, eval_str=True)
    forwards = "overwrite" in signature.parameters

    def consent(args, kwargs):
        if forwards:
            return signature.bind_partial(*args, **kwargs).arguments.get(
                "overwrite", _OVERWRITE.get() or DEFAULT_OVERWRITE
            )
        return kwargs.pop("overwrite", _OVERWRITE.get() or DEFAULT_OVERWRITE)

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def wrapped(*args, **kwargs):
            with output_operation(consent(args, kwargs)):
                return await fn(*args, **kwargs)
    else:

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            with output_operation(consent(args, kwargs)):
                return fn(*args, **kwargs)

    parameters = list(signature.parameters.values())
    if forwards:
        parameters = [p.replace(annotation=_OVERWRITE_TYPE) if p.name == "overwrite" else p for p in parameters]
    else:
        position = next((i for i, p in enumerate(parameters) if p.kind == p.VAR_KEYWORD), len(parameters))
        parameters.insert(
            position,
            inspect.Parameter(
                "overwrite",
                inspect.Parameter.KEYWORD_ONLY,
                default=DEFAULT_OVERWRITE,
                annotation=_OVERWRITE_TYPE,
            ),
        )
    wrapped.__signature__ = signature.replace(parameters=parameters)
    wrapped.__annotations__ = {p.name: p.annotation for p in parameters}
    wrapped.__annotations__["return"] = signature.return_annotation
    wrapped._kinocut_output_policy = True
    return wrapped
