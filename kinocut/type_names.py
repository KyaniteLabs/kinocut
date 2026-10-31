"""Shipped type names: identity, not names.

A class's ``__name__`` is mutable, caller-controlled data. A caller can
name a class anything — a shipped category, a credential-shaped token, a
sentence — and a numeric subclass can override ``__repr__`` and
``__str__``. The only type names this package publishes are therefore
read off the type *object* against a shipped identity map: an exact
builtin gets its category, every subclass gets a fixed placeholder.

The same rule covers caught exceptions. A foreign exception's class name
is its author's string, so :func:`exception_kind` publishes a name only
for exception classes registered here by identity — the interpreter's
builtins, the stdlib classes this package catches on purpose, and this
package's own errors, registered by :mod:`kinocut.errors` at import.
Every other exception is a fixed ``<foreign-exception>`` label, whatever
its class is called.

This module imports nothing from the package: it is the leaf every other
module can reach without a cycle.
"""

from __future__ import annotations

import builtins as _builtins
from typing import Any

__all__ = [
    "BUILTIN_TYPE_NAMES",
    "builtin_type_name",
    "exception_kind",
    "number_text",
    "register_exception_kinds",
    "type_label",
]

#: The type categories a public message may name. Keyed by identity: a
#: caller's subclass that renames itself to a shipped category is still a
#: caller's subclass, and ``type(value)`` is not fooled by a name.
BUILTIN_TYPE_NAMES: dict[type, str] = {
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

#: The longest numeric rendering a message publishes. Beyond this the
#: digits stop being operator-readable and start being payload.
_MAX_NUMBER_CHARS = 24

#: Exception kinds published by identity. Labels are snapshotted when the
#: class is registered, so a later global ``__name__`` mutation changes
#: nothing that is already registered.
_EXCEPTION_KINDS: dict[type, str] = {}


def builtin_type_name(value: Any) -> str | None:
    """The shipped category for an exactly-builtin value, else ``None``.

    >>> builtin_type_name("token")
    'str'
    >>> builtin_type_name(True)
    'bool'
    """
    return BUILTIN_TYPE_NAMES.get(type(value))


def type_label(value: Any) -> str:
    """The shipped category for a value; ``<object>`` for every subclass.

    >>> type_label("token")
    'str'
    >>> type_label(object())
    '<object>'
    """
    name = builtin_type_name(value)
    return name if name is not None else "<object>"


def number_text(value: Any) -> str | None:
    """A bounded numeric rendering, or ``None`` when the value is not numeric.

    An exact builtin renders through its C-level ``repr``, which a caller
    cannot override. A numeric *subclass* may override ``__repr__`` and
    ``__str__``, so it is coerced to the builtin first: only digits can
    come back, and a coercion that fails or runs long publishes the fixed
    ``<number>`` label instead.
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


def register_exception_kinds(classes: list[type] | tuple[type, ...]) -> None:
    """Register exception classes by identity, with snapshotted labels.

    Only classes registered here have their names published by
    :func:`exception_kind`; a subclass of a registered class is NOT
    registered — identity, not inheritance, is the rule, because a
    subclass's name is its author's string.
    """
    for cls in classes:
        if isinstance(cls, type) and issubclass(cls, BaseException):
            _EXCEPTION_KINDS[cls] = cls.__name__


def exception_kind(exc: BaseException) -> str:
    """The kind of a caught failure: a registered identity, or a fixed label.

    The text of an exception routinely embeds the path or the value that
    failed, so it is caller data. The *kind* is the part that tells the
    operator what class of failure this is — and even a kind is only
    published when the class itself is one this interpreter or this
    package shipped; anything else is ``<foreign-exception>``.

    >>> exception_kind(OSError(2, "no such file: /secret/9f3a7c.mp4"))
    'OSError'
    """
    kind = _EXCEPTION_KINDS.get(type(exc))
    return kind if kind is not None else "<foreign-exception>"


def _register_stdlib_kinds() -> None:
    """Snapshot the interpreter's own exception kinds by identity."""
    register_exception_kinds(
        [obj for obj in vars(_builtins).values() if isinstance(obj, type) and issubclass(obj, BaseException)]
    )
    # Stdlib exception classes this package catches and names on purpose.
    # Registered by identity: a caller's class that shadows the name is a
    # different type object and never matches.
    import json as _json
    import subprocess as _subprocess

    for cls in (
        getattr(_json, "JSONDecodeError", None),
        getattr(_subprocess, "TimeoutExpired", None),
        getattr(_subprocess, "CalledProcessError", None),
    ):
        if isinstance(cls, type):
            register_exception_kinds([cls])
    try:  # optional dependency; absent in a core install
        from pydantic import ValidationError as _ValidationError

        register_exception_kinds([_ValidationError])
    except ImportError:  # pragma: no cover - dependency absent
        pass


_register_stdlib_kinds()
