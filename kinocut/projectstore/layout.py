"""Path rules for the private ``.kinocut/`` project store (Plan 00 Task 3).

Layout is pure, side-effect-free path arithmetic. Asset locations are
content-addressed from an ``asset_id`` (``.kinocut/assets/sha256/<digest>/<name>``);
derived evidence uses the parallel ``.kinocut/artifacts/sha256/`` subtree;
records live in ``.kinocut/records/<kind>.jsonl``; indexes and locks each get
their own subtree. Every produced path is a project-relative
:class:`~pathlib.PurePosixPath`, and :func:`contained_path` is the single choke
point that turns a relative path into an absolute one only after proving it
stays inside the resolved project root — the root-containment defense.

All rejections raise the shared contract :class:`MCPVideoError` (never a bare
``ValueError``), so callers see one uniform error shape.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from kinocut.contracts._errors import INVALID_RECORD, contract_error

#: Root of the private store, relative to a project directory.
KINOCUT_DIR = ".kinocut"

# Subtrees under ``.kinocut/``.
_ASSETS = "assets"
_ARTIFACTS = "artifacts"
_BLOBS = "blobs"
_RECORDS = "records"
_INDEXES = "indexes"
_LOCKS = "locks"
_PROJECT_METADATA = "project.json"

# An ``asset_id`` is a lowercase-hex sha256 digest carrying its algorithm prefix.
_ASSET_ID_RE = re.compile(r"^sha256:([0-9a-f]{64})$")
# A record kind is a bounded lowercase identifier (mirrors ``_RECORD_KIND_PATTERN``
# in ``kinocut/contracts/_common.py``) so it is always a safe filename stem.
_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Characters allowed to survive filename sanitization; everything else becomes ``_``.
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_MAX_NAME_LEN = 128


def sanitize_name(name: str) -> str:
    """Return a safe filename *label* — basename only, no traversal, never empty.

    The input is reduced to its POSIX basename, unsafe characters are replaced
    with ``_``, leading dots are stripped so the result is never a dotfile or a
    ``.``/``..`` traversal token, and the length is bounded. An empty or
    all-stripped input degrades to the literal ``asset``.
    """

    base = PurePosixPath(name.replace("\\", "/")).name
    cleaned = _UNSAFE_NAME_CHARS.sub("_", base).lstrip(".")
    if not cleaned or cleaned in {".", ".."}:
        return "asset"
    return cleaned[:_MAX_NAME_LEN]


def asset_relative_path(asset_id: str, name: str) -> PurePosixPath:
    """Content-addressed, project-relative path for an ingested asset.

    ``asset_id`` must be a well-formed ``sha256:<64 hex>`` id; ``name`` is
    sanitized to a bare label. The digest — not the caller-supplied name —
    determines the directory, so identical bytes always resolve to one location.
    """

    match = _ASSET_ID_RE.match(asset_id)
    if match is None:
        raise contract_error(f"malformed asset_id: {asset_id!r}", INVALID_RECORD)
    digest = match.group(1)
    return PurePosixPath(KINOCUT_DIR, _ASSETS, "sha256", digest, sanitize_name(name))


def artifact_relative_path(artifact_id: str, name: str) -> PurePosixPath:
    """Content-addressed, project-relative path for a derived artifact."""

    match = _ASSET_ID_RE.match(artifact_id)
    if match is None:
        raise contract_error(f"malformed artifact_id: {artifact_id!r}", INVALID_RECORD)
    return PurePosixPath(
        KINOCUT_DIR,
        _ARTIFACTS,
        "sha256",
        match.group(1),
        sanitize_name(name),
    )


def blob_relative_path(digest: str) -> PurePosixPath:
    """Canonical project-relative path for one immutable CAS blob."""

    match = _ASSET_ID_RE.match(digest)
    if match is None:
        raise contract_error(f"malformed digest: {digest!r}", INVALID_RECORD)
    return PurePosixPath(KINOCUT_DIR, _BLOBS, "sha256", match.group(1))


def records_relative_path(kind: str) -> PurePosixPath:
    """Project-relative JSONL path for a record ``kind``."""

    if _KIND_RE.match(kind) is None:
        raise contract_error(f"unsafe record kind: {kind!r}", INVALID_RECORD)
    return PurePosixPath(KINOCUT_DIR, _RECORDS, f"{kind}.jsonl")


def records_dir() -> PurePosixPath:
    """Project-relative directory holding per-kind record JSONL files."""

    return PurePosixPath(KINOCUT_DIR, _RECORDS)


def assets_dir() -> PurePosixPath:
    """Project-relative root of the content-addressed asset store."""

    return PurePosixPath(KINOCUT_DIR, _ASSETS, "sha256")


def artifacts_dir() -> PurePosixPath:
    """Project-relative root of the derived artifact store."""

    return PurePosixPath(KINOCUT_DIR, _ARTIFACTS, "sha256")


def blobs_dir() -> PurePosixPath:
    """Project-relative root of the canonical content-addressed blob store."""

    return PurePosixPath(KINOCUT_DIR, _BLOBS, "sha256")


def index_dir() -> PurePosixPath:
    """Project-relative directory holding derived indexes (rebuildable)."""

    return PurePosixPath(KINOCUT_DIR, _INDEXES)


def lock_dir() -> PurePosixPath:
    """Project-relative directory holding the project lock file."""

    return PurePosixPath(KINOCUT_DIR, _LOCKS)


def project_metadata_path() -> PurePosixPath:
    """Project-relative path for the private durable store identity."""

    return PurePosixPath(KINOCUT_DIR, _PROJECT_METADATA)


def contained_path(root: Path, relative: PurePosixPath | str) -> Path:
    """Join ``relative`` onto ``root`` and prove the result stays inside ``root``.

    This is the root-containment defense: a crafted digest, name, or record kind
    can never escape the project tree. The absolute candidate is resolved and
    must equal ``root`` or have ``root`` among its parents, else the path is
    rejected as an escape attempt.
    """

    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise contract_error(f"path escapes project root: {relative!r}", INVALID_RECORD)
    return candidate
