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

from typing import Any

from ._errors import SoundContractError

#: The contract errors this package raises on purpose. Their message is
#: package-authored guidance, so it is safe to publish again. Any other
#: exception's text may embed a path the caller submitted, so only its
#: kind is published.
CONTRACT_ERRORS = (SoundContractError,)


def rejected_value(value: Any) -> str:
    """Name a refused value by its type, never by its content.

    A number is repeated: the operator needs the number to correct the
    call, and a number is not a secret. Anything else is named by type.
    """
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return str(value)
    return type(value).__name__


def exception_kind(failure: BaseException) -> str:
    """Name a caught exception by its class, never by its text."""
    return type(failure).__name__


def reason(exc: BaseException) -> str:
    """The reason of a failure, when the reason is ours to publish.

    A contract error's message is package-authored guidance, so it is
    safe to publish again. Any other exception's text may embed a path
    the caller submitted, so only its kind is published.
    """
    if isinstance(exc, CONTRACT_ERRORS):
        return str(exc)
    return exception_kind(exc)
