"""Project-relative location safety — one rule shared by models and the store.

A stored *location* (an asset's ``original_location``, an evidence ref) must be
a project-relative path with no way to escape the project tree or smuggle a
remote resource. :func:`location_violation` returns a human-readable reason when
a value is unsafe, or ``None`` when it is safe, so each caller can raise in its
own idiom — a Pydantic ``ValueError`` inside a model validator, or a stable
contract ``MCPVideoError`` at the store boundary — without duplicating the rule.
"""

from __future__ import annotations

import re

# A leading ``scheme:`` (http, file, data, ...) or a Windows drive letter. Both
# would point outside the project, so both are rejected as non-relative.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def location_violation(value: str) -> str | None:
    """Return why ``value`` is an unsafe stored location, or ``None`` if safe.

    Rejected: empty strings, NUL/control characters, URL schemes, absolute or
    home paths, Windows drive/UNC paths, parent-directory traversal, and empty
    path components (``a//b``). Everything else is a plain project-relative path.
    """

    if value == "":
        return "location must not be empty"
    if any(ord(char) < 0x20 for char in value):
        return "location must not contain control characters"
    if "://" in value or _SCHEME_RE.match(value):
        return "location must not be a URL or scheme"
    if value.startswith(("/", "~", "\\")):
        return "location must be project-relative, not absolute"
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if ".." in parts:
        return "location must not traverse parent directories"
    if "" in parts:
        return "location must not contain empty path components"
    return None
