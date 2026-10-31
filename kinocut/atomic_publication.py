"""Descriptor-anchored, identity-checked publication of an individual artifact."""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from collections.abc import Callable, Iterator

from .errors import MCPVideoError
from .type_names import exception_kind
from .staged_writers import owned_stage


def _unsafe(message: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code="unsafe_path")


def _partial_output(message: str) -> MCPVideoError:
    return MCPVideoError(
        message,
        error_type="processing_error",
        code="partial_output_publication",
        suggested_action={"action": "inspect_output", "prior_output_preserved": False},
    )


def _open_root_descriptor() -> int:
    """Open the filesystem root as an anchor descriptor.

    ``O_PATH`` is requested because hardened hosts (seccomp/LSM policies, some
    container runtimes) deny opening ``/`` with read permission. A read-open
    of the root is not needed to walk the ancestry: every component below it
    is opened with ``O_NOFOLLOW`` relative to the parent descriptor, and
    ``O_PATH`` descriptors are valid ``dir_fd`` arguments. Without this
    fallback the whole atomic-publication path fails on such hosts with
    "Atomic output could not preserve directory identity: PermissionError".
    """
    try:
        return os.open(os.path.sep, os.O_RDONLY | os.O_DIRECTORY)
    except PermissionError:
        if not hasattr(os, "O_PATH"):
            raise
        return os.open(os.path.sep, os.O_PATH | os.O_DIRECTORY)


def _open_directory(directory: str) -> int:
    """Walk canonical ancestry without following a concurrently planted symlink."""
    descriptor = _open_root_descriptor()
    try:
        for component in directory.split(os.path.sep):
            if not component:
                continue
            try:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                # A concurrent creator must still pass the no-follow open.
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class _Directory:
    def __init__(self, path: str):
        from .publication_windows import lock_directory_ancestry, windows_supported

        self.path, self.fd, self.close_windows = path, None, None
        if os.name == "posix" and hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd:
            self.fd = _open_directory(path)
        elif windows_supported():
            self.close_windows = lock_directory_ancestry(path)
        else:
            raise _unsafe("Atomic publication requires supported directory anchoring")
        try:
            self.identity = os.fstat(self.fd) if self.fd is not None else os.stat(path)
        except BaseException:
            self.close()
            raise

    def check(self):
        current = os.stat(self.path, follow_symlinks=False)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
            self.identity.st_dev,
            self.identity.st_ino,
        ):
            raise _unsafe("Output directory changed during publication")

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.close_windows is not None:
            self.close_windows()
            self.close_windows = None

    def options(self):
        return {"dir_fd": self.fd} if self.fd is not None else {}

    def name(self, basename):
        return basename if self.fd is not None else os.path.join(self.path, basename)


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
        from .ffmpeg_helpers import _note_operation_write

        _note_operation_write(temporary)
        with owned_stage(temporary, fd):
            validate(temporary)
            yield temporary
            anchor.check()
            validate(temporary)
        anchor.check()
        validate(final)
        current = os.stat(anchor.name(stage), follow_symlinks=False, **anchor.options())
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise _unsafe("Output staging file changed during publication")
        from .output_policy import _OVERWRITE

        if anchor.fd is None:
            os.close(fd)
            fd = None
        if _OVERWRITE.get() is True:
            if anchor.fd is not None:
                os.replace(stage, basename, src_dir_fd=anchor.fd, dst_dir_fd=anchor.fd)
            else:
                os.replace(temporary, final)
        else:
            # link() creates the destination exclusively: a target planted after
            # validation must survive, even if it appeared during rendering.
            os.link(
                anchor.name(stage),
                anchor.name(basename),
                **({"src_dir_fd": anchor.fd, "dst_dir_fd": anchor.fd} if anchor.fd is not None else {}),
                follow_symlinks=False,
            )
        published = True
        try:
            anchor.check()
        except (OSError, MCPVideoError) as exc:
            raise _partial_output(
                "Output directory changed after publication; inspect the output before reuse"
            ) from exc
        current = os.stat(anchor.name(basename), follow_symlinks=False, **anchor.options())
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise _partial_output("Output identity changed after publication; inspect the output before reuse")
        _note_operation_write(final)
    except OSError as exc:
        if published:
            raise _partial_output("Published output could not be verified; inspect the output before reuse") from exc
        raise _unsafe(f"Atomic output could not preserve directory identity: {exception_kind(exc)}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if anchor is not None:
            if stage is not None and identity is not None:
                with contextlib.suppress(OSError):
                    current = os.stat(anchor.name(stage), follow_symlinks=False, **anchor.options())
                    if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                        os.unlink(anchor.name(stage), **anchor.options())
            anchor.close()
