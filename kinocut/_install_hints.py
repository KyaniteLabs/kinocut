"""Install hints that pin the version that is actually running.

Recovery surfaces used to hardcode the release they were written against,
so a user on a newer release who followed the hint reinstalled an older
one (audit row 78: the missing-Whisper recovery kept recommending a stale
pin). The helpers here interpolate the running distribution's version
instead, which means a hint can only ever tell the user to reinstall the
release they already have.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

__all__ = ["pinned_requirement", "pip_install_hint", "running_version"]


def running_version() -> str:
    """The version of the kinocut distribution that is actually running."""
    try:
        return _distribution_version("kinocut")
    except PackageNotFoundError:
        # A source tree that was never installed has no distribution
        # metadata; releases keep the package constant in sync, so it is
        # the best remaining answer for "what is running".
        from . import __version__

        return __version__


def pinned_requirement(extra: str | None = None) -> str:
    """A pip requirement string that pins the running version.

    The distribution name, the requested extras and the pinned running
    version are concatenated in pip requirement syntax; pass ``extra=None``
    for the bare distribution.
    """
    spec = f"kinocut[{extra}]" if extra else "kinocut"
    return f"{spec}=={running_version()}"


def pip_install_hint(extra: str | None = None, *, quoted: bool = True) -> str:
    """The ``pip install`` command that reinstalls the running version.

    ``quoted`` preserves the historical spellings of the recovery text:
    extras were shown quoted, the bare package unquoted.
    """
    requirement = pinned_requirement(extra)
    target = f'"{requirement}"' if quoted else requirement
    return f"pip install {target}"
