"""Value-free naming for the sound package's contract errors.

The sound package is deliberately independent of ``kinocut``: it ships its
own errors, its own codes, and its own contract vocabulary. It therefore
carries its own small naming helper rather than importing one across the
package boundary.

The rule is the same as the rest of the repository: a number is repeated
because the operator needs it to correct the call, and everything else — a
string, a path, the text of a caught exception — is named by type only.
A contract message says which argument was refused and what was expected,
never what the caller passed.

A contract error is the exception, in the same way it is in ``kinocut``:
its message is package-authored guidance, so :func:`reason` may publish it
again. A refusal must not throw away the reason it gives.
"""

from __future__ import annotations

import builtins as _builtins
from typing import Any

from ._errors import SoundContractError

#: The contract errors this package raises on purpose. Their message is
#: package-authored guidance, so it is safe to publish again. Any other
#: exception's text may embed a path the caller submitted, so only its
#: kind is published.
CONTRACT_ERRORS = (SoundContractError,)

#: The type categories a contract message may name. Keyed by identity: a
#: caller's subclass that renames itself to a shipped category is still a
#: caller's subclass. This package is deliberately independent of
#: ``kinocut``, so it carries its own copy of the identity map.
_TYPE_NAMES: dict[type, str] = {
    str: "str",
    int: "int",
    float: "float",
    bool: "bool",
    bytes: "bytes",
    list: "list",
    dict: "dict",
    tuple: "tuple",
    set: "set",
    type(None): "NoneType",
}

#: The longest numeric rendering a message publishes.
_MAX_NUMBER_CHARS = 24

#: Exception kinds published by identity; labels are snapshotted at
#: registration so a later global ``__name__`` mutation changes nothing.
_EXCEPTION_KINDS: dict[type, str] = {}


def _type_label(value: Any) -> str:
    """The shipped category for a value; ``<object>`` for every subclass."""
    name = _TYPE_NAMES.get(type(value))
    return name if name is not None else "<object>"


def _number_text(value: Any) -> str | None:
    """A bounded numeric rendering, or ``None`` for a non-numeric value.

    An exact builtin renders through its C-level ``repr``, which a caller
    cannot override. A numeric subclass is coerced to the builtin first,
    so only digits can come back.
    """
    if type(value) in (int, float):
        return repr(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        coerced = int(value) if isinstance(value, int) else float(value)
        text = repr(coerced)
    except (ArithmeticError, TypeError, ValueError):
        return "<number>"
    return text if len(text) <= _MAX_NUMBER_CHARS else "<number>"


def _register_exception_kinds(classes: list[type] | tuple[type, ...]) -> None:
    for cls in classes:
        if isinstance(cls, type) and issubclass(cls, BaseException):
            _EXCEPTION_KINDS[cls] = cls.__name__


def _register_known_kinds() -> None:
    """Snapshot the interpreter's and this package's kinds by identity."""
    import json as _json
    import subprocess as _subprocess

    _register_exception_kinds(
        [obj for obj in vars(_builtins).values() if isinstance(obj, type) and issubclass(obj, BaseException)]
    )
    for cls in (
        getattr(_json, "JSONDecodeError", None),
        getattr(_subprocess, "TimeoutExpired", None),
        getattr(_subprocess, "CalledProcessError", None),
        SoundContractError,
    ):
        if isinstance(cls, type):
            _register_exception_kinds([cls])


_register_known_kinds()


def rejected_value(value: Any) -> str:
    """Name a refused value by its shipped category, never by its content.

    A number is repeated: the operator needs the number to correct the
    call, and a number is not a secret. Everything else is named by its
    category — read off the type object by identity, because a class's
    ``__name__`` is mutable caller data and a numeric subclass can
    override ``__repr__``/``__str__``; a subclass is coerced to the
    builtin first, so only digits can come back.
    """
    number = _number_text(value)
    if number is not None:
        return number
    return _type_label(value)


def exception_kind(failure: BaseException) -> str:
    """Name a caught exception by a registered identity, never by its text.

    Only the interpreter's own exception classes and this package's
    contract error have their names published; anything else — including a
    caller's class that shadows a known name — is the fixed
    ``<foreign-exception>`` label, because a foreign class's name is its
    author's string.
    """
    kind = _EXCEPTION_KINDS.get(type(failure))
    return kind if kind is not None else "<foreign-exception>"


def reason(exc: BaseException) -> str:
    """The reason of a failure, when the reason is ours to publish.

    A contract error's message is package-authored guidance, so it is
    safe to publish again. Any other exception's text may embed a path
    the caller submitted, so only its kind is published.
    """
    if isinstance(exc, CONTRACT_ERRORS):
        return str(exc)
    return exception_kind(exc)
