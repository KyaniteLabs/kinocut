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

__all__ = [
    "REPUBLISHABLE",
    "exception_kind",
    "invalid_parameter",
    "reason",
    "rejected_value",
]


def rejected_value(value: Any) -> str:
    """Describe a rejected value without repeating it.

    A number is safe to repeat: it is not a secret, and the operator needs
    it to correct the call. Everything else is the caller's own data and is
    named by its type only, so a path or a token never reaches the payload.

    >>> rejected_value(30)
    '30'
    >>> rejected_value("sk-secret")
    'str'
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return type(value).__name__
    return repr(value)


def exception_kind(exc: BaseException) -> str:
    """The kind of a caught failure, without its text.

    The text of an exception routinely embeds the path or the value that
    failed, so it is caller data. The class name is the part that tells the
    operator what happened.

    >>> exception_kind(OSError(2, "no such file: /secret/9f3a7c.mp4"))
    'OSError'
    """
    return type(exc).__name__


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
    if isinstance(exc, REPUBLISHABLE):
        return str(exc)
    return exception_kind(exc)
