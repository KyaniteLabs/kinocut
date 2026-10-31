"""Value-free refusals for the public validator surface.

A refusal names the argument and the failure. It never repeats what the
caller passed: that string can be a path, a codec name, or a
credential-shaped token, and it must not travel back out to the caller.

The rule this module enforces is the one the repository already ships for
nested job specs: a number is not a secret and the operator needs it to
correct the call, so a number is repeated; anything else is named by type
only. Applying it uniformly means an interpolation of a rejected value goes
through :func:`rejected_value` rather than through the f-string directly.

A caught exception's text is caller data too — an ``OSError`` names the path
that failed — so a foreign exception's text is never copied into a message.
Its *kind* is reported instead, which is the part that tells the operator
what class of failure they are looking at.

Our own errors are the exception: their text was written here, under the
rule above, so :func:`reason` may publish it again. A refusal must not
throw away the reason it gives.
"""

from __future__ import annotations

from typing import Any

from .errors import MCPVideoError
from .type_names import exception_kind, number_text, type_label

import kinocut.errors as _package_errors

__all__ = [
    "REPUBLISHABLE",
    "exception_kind",
    "invalid_parameter",
    "likely_cause",
    "own_reason",
    "reason",
    "rejected_value",
]


def rejected_value(value: Any) -> str:
    """Describe a rejected value without repeating it.

    A number is safe to repeat: it is not a secret, and the operator needs
    it to correct the call. Everything else is the caller's own data and is
    named by its shipped type category — never by the class's ``__name__``,
    which is mutable caller data, and never through the value's own
    ``__repr__``/``__str__``, which a subclass can override. A numeric
    subclass is coerced to the builtin first, so only digits can come back.

    >>> rejected_value(30)
    '30'
    >>> rejected_value("sk-secret")
    'str'
    """
    number = number_text(value)
    if number is not None:
        return number
    return type_label(value)


#: ``exception_kind`` is re-exported from :mod:`kinocut.type_names` (it
#: is also called by :func:`reason` below): a caught failure is named by a
#: registered identity — the interpreter's builtins, the stdlib classes
#: this package catches, this package's own errors — and every other
#: exception is the fixed ``<foreign-exception>`` label. A foreign
#: exception's class name is its author's string, so it is never published.


def invalid_parameter(name: str, expectation: str, value: Any = None) -> str:
    """A refusal that names the parameter and the expectation, never the value.

    ``name`` is the parameter's own name and ``expectation`` is shipped
    guidance — the allowed set, the bound, the shape. The rejected value is
    described through :func:`rejected_value`, so a caller-controlled string
    cannot reach the message even by accident.

    The result is a plain message string, so the same refusal serves a
    raised error and a structured tool result.
    """
    message = f"{name} {expectation}"
    if value is not None:
        message = f"{message} (got {rejected_value(value)})"
    return message


#: The errors this package raises on purpose. Their text was written here,
#: under the value-free rule, so it is safe to publish again. A foreign
#: exception's text routinely embeds the path that failed, so only its
#: kind is published.
REPUBLISHABLE = (MCPVideoError,)

#: The identity set behind :func:`reason`. Membership is by exact type
#: object, not inheritance: every error class this package defines in
#: ``kinocut.errors`` at import time is in the set, and a caller's or
#: plugin's subclass of any of them is NOT — its name and text are its
#: author's strings, so it is published only as its kind.
_PACKAGE_ERROR_IDENTITIES = frozenset(
    obj for obj in vars(_package_errors).values() if isinstance(obj, type) and issubclass(obj, Exception)
)


#: Private provenance token: bound to instances only by this module's own
#: construction path, and checked by exact type plus token. A caller's
#: subclass of :class:`PackageReason` — however it names or renders
#: itself — fails both checks, so its text is never republished.
_PROVENANCE_TOKEN = object()


class PackageReason(str):
    """A cause string this package authored at a fixed construction site.

    Text written by this package is bounded by the same rule as every other
    public message — it names the condition and never repeats a caller's
    value — so a diagnostic channel can republish it verbatim. Text this
    package did not write must never be wrapped: the wrapper is the claim
    that makes republication safe.

    The token is private on purpose. Provenance is a claim only this
    module can mint, checked by exact type and token — never by
    :func:`isinstance`, which any caller's subclass satisfies.
    """

    __slots__ = ("_token",)

    def __new__(cls, text: str) -> PackageReason:
        self = super().__new__(cls, text)
        self._token = _PROVENANCE_TOKEN
        return self


def own_reason(text: str) -> str:
    """Mark a package-authored cause so diagnostics keep the reason.

    The return value is still an ordinary string; the wrapper type only
    records who wrote it.
    """
    return PackageReason(text)


def likely_cause(cause: str) -> str:
    """The ``likely cause`` text of a plan/review/package refusal.

    A cause this package authored (:func:`own_reason`) carries the bounded
    diagnostic the operator needs, so it survives verbatim. Anything else
    is caller data — a path, an id, a foreign exception's text — and is
    named only by its type, exactly like every other public message.

    The check is exact type plus private token: a caller's subclass of the
    marker (or any other string) is treated as caller data.
    """
    if type(cause) is PackageReason and cause._token is _PROVENANCE_TOKEN:
        return cause
    return rejected_value(cause)


def reason(exc: BaseException) -> str:
    """The reason of a failure, when the reason is ours to publish.

    A message this package wrote is safe to publish again: the rule every
    construction site follows is that a message names the condition and
    never repeats a caller's value. A foreign exception's text routinely
    embeds the path that failed, so only its kind is published.

    >>> reason(MCPVideoError("Unknown preset. Available: ['a']"))
    'Unknown preset. Available: [\'a\']'
    >>> reason(OSError(2, "no such file: /secret/9f3a7c.mp4"))
    'OSError'
    """
    if type(exc) in _PACKAGE_ERROR_IDENTITIES:
        return str(exc)
    return exception_kind(exc)
