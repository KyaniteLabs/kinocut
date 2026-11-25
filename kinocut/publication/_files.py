"""Descriptor-anchored, identity-checked publication of individual files."""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
import stat
from collections.abc import Callable, Iterator

from ..errors import MCPVideoError
from ..type_names import exception_kind
from ._anchor import _Directory, _partial_output, _rename_exclusive, _same_inode, _unsafe
from ._operation import _OVERWRITE, _record_write
from ._policy import _owns_durable_receipt
from ._receipts import _witness_receipt_stage
from ._staging import owned_stage

_LINK_UNSUPPORTED = {errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV}


def _remove_owned(anchor: _Directory, name: str, identity: os.stat_result) -> None:
    with contextlib.suppress(OSError):
        current = os.stat(anchor.name(name), follow_symlinks=False, **anchor.options())
        if _same_inode(current, identity):
            os.unlink(anchor.name(name), **anchor.options())


def _publish_without_overwrite(
    anchor: _Directory, stage: str, basename: str, identity: os.stat_result
) -> os.stat_result:
    try:
        os.link(
            anchor.name(stage),
            anchor.name(basename),
            **({"src_dir_fd": anchor.fd, "dst_dir_fd": anchor.fd} if anchor.fd is not None else {}),
            follow_symlinks=False,
        )
    except OSError as exc:
        if exc.errno not in _LINK_UNSUPPORTED and getattr(exc, "winerror", None) != 1:
            raise
        anchor.check()
        _rename_exclusive(anchor, stage, basename)
    return identity


@contextlib.contextmanager
def anchored_output(path: str, validate: Callable[[str], str]) -> Iterator[str]:
    """Publish only the original regular staging inode in the anchored directory."""
    final = os.path.realpath(validate(path))
    validate(final)
    directory, basename = os.path.split(final)
    anchor = None
    stage = None
    identity = None
    fd = None
    published = False
    try:
        anchor = _Directory(directory)
        stage = f".kinocut_tmp_{secrets.token_hex(16)}{os.path.splitext(final)[1] or '.tmp'}"
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(anchor.name(stage), flags, 0o600, **anchor.options())
        identity = os.fstat(fd)
        anchor.check()
        temporary = os.path.join(directory, stage)
        _record_write(temporary, identity, published=False)
        with owned_stage(temporary, fd):
            validate(temporary)
            yield temporary
            anchor.check()
            validate(temporary)
        anchor.check()
        validate(final)
        current = os.stat(anchor.name(stage), follow_symlinks=False, **anchor.options())
        if not stat.S_ISREG(current.st_mode) or not _same_inode(current, identity):
            raise _unsafe("Output staging file changed during publication")
        _witness_receipt_stage(final, temporary, identity)

        if anchor.fd is None:
            os.close(fd)
            fd = None
        if _OVERWRITE.get() is True or _owns_durable_receipt(final):
            if anchor.fd is not None:
                os.replace(stage, basename, src_dir_fd=anchor.fd, dst_dir_fd=anchor.fd)
            else:
                os.replace(temporary, final)
            published_identity = identity
        else:
            published_identity = _publish_without_overwrite(anchor, stage, basename, identity)
        published = True
        try:
            anchor.check()
        except (OSError, MCPVideoError) as exc:
            raise _partial_output(
                "Output directory changed after publication; inspect the output before reuse"
            ) from exc
        current = os.stat(anchor.name(basename), follow_symlinks=False, **anchor.options())
        if not stat.S_ISREG(current.st_mode) or not _same_inode(current, published_identity):
            raise _partial_output("Output identity changed after publication; inspect the output before reuse")
        _record_write(final, current, published=True)
    except OSError as exc:
        if published:
            raise _partial_output("Published output could not be verified; inspect the output before reuse") from exc
        raise _unsafe(f"Atomic output could not preserve directory identity: {exception_kind(exc)}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if anchor is not None:
            if stage is not None and identity is not None:
                _remove_owned(anchor, stage, identity)
            anchor.close()
