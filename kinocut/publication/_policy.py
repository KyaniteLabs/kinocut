"""Location policy and evidence required to replace existing files."""

import os
import re
import stat

from ..agent_homes import inside_agent_scratch_or_refuse, require_absolute_under_hermes
from ..errors import MCPVideoError
from ._ledger import owns as owns_output
from ._operation import _OVERWRITE, _owns_operation_output, _reject_self_overwrite
from ._staging import is_staged_output

_BLOCKED_OUTPUT_PREFIXES = (
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/private/etc",
    "/private/var/db",
    "/private/var/log",
    "/private/var/root",
    "/proc",
    "/root",
    "/sbin",
    "/sys",
    "/System",
    "/usr",
    "/var/db",
    "/var/log",
    "/var/root",
)
_SENSITIVE_HOME_PARTS = {
    ".aws",
    ".azure",
    ".config",
    ".docker",
    ".gnupg",
    ".kube",
    ".ssh",
    ".hermes",
    ".claude",
    ".codex",
    ".cursor",
    ".gemini",
    ".kimi",
    ".opencode",
    ".openclaw",
    ".clawdbot",
    ".grok",
    ".zcode",
    ".continue",
}
_SAFE_EXISTING_OUTPUT_SUFFIXES = frozenset(
    {
        ".aac",
        ".aif",
        ".aiff",
        ".avi",
        ".flac",
        ".gif",
        ".jpg",
        ".jpeg",
        ".m4a",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp3",
        ".mp4",
        ".ogg",
        ".opus",
        ".png",
        ".wav",
        ".webm",
        ".webp",
    }
)


def _validate_artifact_location(path: str, label: str) -> str:
    """Reject unsafe locations for outputs and structured artifact inputs."""
    if "\x00" in path:
        raise MCPVideoError(
            f"{label} contains null bytes",
            error_type="validation_error",
            code="invalid_output_path",
        )
    require_absolute_under_hermes(path, label)
    raw_parts = re.split(r"[\\/]+", path)
    if ".." in raw_parts:
        raise MCPVideoError(
            f"{label} contains directory traversal",
            error_type="validation_error",
            code="invalid_output_path",
        )
    if os.path.islink(path):
        raise MCPVideoError(
            f"{label} resolves through a symlink",
            error_type="validation_error",
            code="unsafe_path",
        )

    resolved = os.path.realpath(path)
    if any(resolved == prefix or resolved.startswith(prefix + os.sep) for prefix in _BLOCKED_OUTPUT_PREFIXES):
        raise MCPVideoError(
            f"{label} escapes safe directory",
            error_type="validation_error",
            code="unsafe_path",
        )

    if inside_agent_scratch_or_refuse(resolved, label):
        return resolved

    home = os.path.realpath(os.path.expanduser("~"))
    if resolved == home or resolved.startswith(home + os.sep):
        rel_parts = set(os.path.relpath(resolved, home).split(os.sep))
        if rel_parts & _SENSITIVE_HOME_PARTS:
            raise MCPVideoError(
                f"{label} targets a sensitive home directory",
                error_type="validation_error",
                code="unsafe_path",
            )

    return resolved


def _owns_durable_receipt(resolved: str) -> bool:
    """True when ``resolved`` is the active durable_receipt_ownership target with a verified witness."""
    from ._receipts import _RECEIPT, _proof

    receipt = _RECEIPT.get()
    if receipt is None:
        return False
    target, witnesses = receipt
    if os.path.realpath(str(target)) != resolved:
        return False
    try:
        current = os.stat(resolved, follow_symlinks=False)
    except OSError:
        return False
    if not stat.S_ISREG(current.st_mode):
        return False
    directory = target.parent / f".{target.name}.ownership"
    if directory.is_symlink():
        return False
    expected = _proof(directory, current)
    if expected not in witnesses or expected.is_symlink():
        return False
    try:
        wstat = os.stat(expected, follow_symlinks=False)
    except OSError:
        return False
    return (wstat.st_dev, wstat.st_ino) == (current.st_dev, current.st_ino)


def _validate_write_path(
    path: str,
    *,
    allowed_existing_suffixes: frozenset[str],
    label: str,
    allow_recorded: bool = False,
) -> str:
    """Require consent and job ownership before replacing non-media outputs."""
    if "\x00" not in path:
        _reject_self_overwrite(path)
    resolved = _validate_artifact_location(path, label)
    if os.path.isdir(resolved):
        return path

    if os.path.exists(resolved):
        operation_owned = _owns_operation_output(resolved)
        durable_owned = _owns_durable_receipt(resolved)
        recorded_owned = allow_recorded and owns_output(resolved)
        if is_staged_output(path) and operation_owned:
            return path
        suffix = os.path.splitext(resolved)[1].lower()
        permitted_media = suffix in allowed_existing_suffixes and suffix in _SAFE_EXISTING_OUTPUT_SUFFIXES
        if not permitted_media and not (operation_owned or durable_owned or recorded_owned):
            raise MCPVideoError(
                f"Refusing to overwrite an existing file at {label.lower()}",
                error_type="validation_error",
                code="unsafe_path",
            )
        if _OVERWRITE.get() is not True and not durable_owned:
            raise MCPVideoError(
                f"{label} already exists; pass overwrite=true to replace permitted outputs",
                error_type="validation_error",
                code="output_exists",
            )
    return path


def _validate_output_path(path: str) -> str:
    """Validate an output path before FFmpeg writes with ``-y``.

    Kinocut intentionally lets users write normal media artifacts around their
    projects and temp directories. It must not overwrite system files, symlink
    targets, sensitive home dotfiles, or obviously non-media source/config files.

    This is a prospective precheck. ``_atomic_output`` binds registered producer
    writes to an owned staging descriptor and anchors each file's publication.
    These protections do not provide a universal integrity guarantee against
    concurrent hostile writers in the destination directory.
    """
    return _validate_write_path(path, allowed_existing_suffixes=_SAFE_EXISTING_OUTPUT_SUFFIXES, label="Output path")


def _validate_artifact_path(path: str, *, allow_recorded: bool = False) -> str:
    """Validate provenance writes; existing artifacts need ownership and overwrite consent."""
    return _validate_write_path(
        path,
        allowed_existing_suffixes=frozenset(),
        label="Artifact path",
        allow_recorded=allow_recorded,
    )
