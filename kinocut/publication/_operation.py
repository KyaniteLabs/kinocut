"""Explicit overwrite consent and isolated ownership for a single tool call."""

from __future__ import annotations

import contextlib
import functools
import inspect
import os
from collections.abc import Callable
from contextvars import ContextVar
from typing import Annotated, Any

from pydantic import Field

from ..defaults import DEFAULT_OVERWRITE
from ..errors import MCPVideoError
from ._ledger import _record_identity

_OVERWRITE: ContextVar[bool | None] = ContextVar("kinocut_overwrite", default=None)
_OVERWRITE_TYPE = Annotated[
    bool,
    Field(strict=True, description="Allow replacing existing media files."),
]


_OPERATION_INPUTS: ContextVar[frozenset[str]] = ContextVar("kinocut_operation_inputs", default=frozenset())
_OPERATION_WRITES: ContextVar[dict[str, tuple[int, int]] | None] = ContextVar("kinocut_operation_writes", default=None)
_ON_PUBLISH: ContextVar[Callable[[str], None] | None] = ContextVar("kinocut_on_publish", default=None)


def _owns_operation_output(path: str) -> bool:
    """A filename alone does not prove that this job created the current file."""
    expected = (_OPERATION_WRITES.get() or {}).get(os.path.realpath(path))
    if expected is None:
        return False
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return expected == (current.st_dev, current.st_ino)


def _record_operation_input(resolved: str) -> None:
    """Record a validated input path for the current operation scope."""
    if _owns_operation_output(resolved):
        return
    _OPERATION_INPUTS.set(_OPERATION_INPUTS.get() | {resolved})


def _note_operation_write(path: str) -> None:
    """Record a successful legacy writer without an anchored descriptor."""
    resolved = os.path.realpath(path)
    _record_write(resolved, os.stat(path, follow_symlinks=False), published=True)


def _record_write(resolved: str, current: os.stat_result, *, published: bool) -> None:
    writes = _OPERATION_WRITES.get()
    if writes is None:
        writes = {}
        _OPERATION_WRITES.set(writes)
    writes[resolved] = (current.st_dev, current.st_ino)
    if not published:
        return
    if notify := _ON_PUBLISH.get():
        notify(resolved)
    _record_identity(resolved, current)


def _reset_operation_inputs(*, preserve_writes: bool = False) -> None:
    """Start a fresh operation scope for the self-overwrite guard.

    MCP tool calls never need this (context isolation scopes them already);
    long-running direct callers may use it between distinct operations.
    """
    _OPERATION_INPUTS.set(frozenset())
    if not preserve_writes:
        _OPERATION_WRITES.set({})


def _reject_self_overwrite(path: str) -> None:
    """Protect operation inputs, including hardlinked aliases."""
    recorded = _OPERATION_INPUTS.get()
    if not recorded:
        return
    resolved_output = os.path.realpath(path)
    for input_path in recorded:
        if resolved_output == os.path.realpath(input_path):
            raise MCPVideoError(
                "output path aliases an input of this operation",
                error_type="validation_error",
                code="invalid_output_path",
            )
    if not os.path.exists(path):
        return
    for input_path in recorded:
        try:
            if os.path.samefile(path, input_path):
                raise MCPVideoError(
                    "output path aliases an input of this operation (same file)",
                    error_type="validation_error",
                    code="invalid_output_path",
                )
        except OSError:
            # The realpath compare above already ran; an unreadable path here
            # cannot be proven identical, so fail open for the hardlink probe.
            continue


@contextlib.contextmanager
def output_operation(overwrite: bool = DEFAULT_OVERWRITE):
    """Scope consent and input/output ownership to this job, including worker threads."""
    if type(overwrite) is not bool:
        raise MCPVideoError(
            "overwrite must be an explicit boolean", error_type="validation_error", code="invalid_parameter"
        )
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


def read_only(fn: Any) -> Any:
    """Mark a handler that never writes media, so it gets no ``overwrite`` parameter."""
    fn._kinocut_read_only = True
    return fn


def with_output_policy(fn: Any) -> Any:
    """Expose a strict ``overwrite=false`` keyword on each MCP handler that can write media."""
    if getattr(fn, "_kinocut_output_policy", False) or getattr(fn, "_kinocut_read_only", False):
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
