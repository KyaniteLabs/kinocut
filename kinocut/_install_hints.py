"""Install hints that pin the version that is actually running.

Recovery surfaces used to hardcode the release they were written against,
so a user on a newer release who followed the hint reinstalled an older
one (audit row 78: the missing-Whisper recovery kept recommending a stale
pin). The helpers here interpolate the running distribution's version
instead, which means a hint can only ever tell the user to reinstall the
release they already have.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

__all__ = ["pinned_requirement", "pip_install_hint", "running_version"]

_VERSION_PARTS = re.compile(r"\d+")


def _version_key(version: str) -> tuple[int, ...]:
    """Numeric components of a release string, for ordering two releases."""
    return tuple(int(part) for part in _VERSION_PARTS.findall(version.split("+", 1)[0]))


def running_version() -> str:
    """The version of the kinocut distribution that is actually running.

    An editable or development checkout keeps its own ``__version__`` while
    the installed distribution metadata can still name an older release;
    the code that is running is the truth in that case, so the newer of the
    two wins. A source tree that was never installed has no distribution
    metadata at all and falls back to the package constant.
    """
    from . import __version__

    try:
        installed = _distribution_version("kinocut")
    except PackageNotFoundError:
        return __version__
    try:
        if _version_key(__version__) > _version_key(installed):
            return __version__
    except ValueError:
        return __version__
    return installed


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
