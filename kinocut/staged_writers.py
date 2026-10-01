"""Context-owned staging descriptors shared by publication and process runners."""

from __future__ import annotations

import contextlib
import os
import threading
from contextvars import ContextVar

from .errors import MCPVideoError


class _Stage:
    def __init__(self, descriptor):
        self.fd = descriptor
        self.identity = os.fstat(descriptor)
        self.active = True
        self.leases = 0
        self.lock = threading.Lock()

    def duplicate(self):
        with self.lock:
            if not self.active:
                raise MCPVideoError("Staging transaction has ended", code="unsafe_path")
            try:
                current = os.fstat(self.fd)
                if (current.st_dev, current.st_ino) != (self.identity.st_dev, self.identity.st_ino):
                    raise MCPVideoError("Staging descriptor identity changed", code="unsafe_path")
                descriptor = os.dup(self.fd)
                self.leases += 1
                return descriptor
            except OSError as exc:
                raise MCPVideoError("Staging descriptor is unavailable", code="unsafe_path") from exc

    def release(self, descriptor):
        try:
            os.close(descriptor)
        finally:
            with self.lock:
                self.leases -= 1


_STAGES: ContextVar[dict[str, _Stage] | None] = ContextVar("kinocut_owned_stages", default=None)
# Explicit muxers replace suffix inference when FFmpeg receives a descriptor path.
_MUXERS = {
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".m4a": "ipod",
    ".mov": "mov",
    ".mkv": "matroska",
    ".webm": "webm",
    ".avi": "avi",
    ".ts": "mpegts",
    ".wav": "wav",
    ".mp3": "mp3",
    ".aac": "adts",
    ".flac": "flac",
    ".ogg": "ogg",
    ".opus": "opus",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".gif": "gif",
    ".png": "image2",
    ".jpg": "image2",
    ".jpeg": "image2",
    ".webp": "webp",
}
_IMAGE_CODECS = {".png": "png", ".jpg": "mjpeg", ".jpeg": "mjpeg", ".webp": "webp"}


def is_staged_output(path: str) -> bool:
    return os.path.abspath(path) in (_STAGES.get() or {})


@contextlib.contextmanager
def owned_stage(path: str, descriptor: int):
    stage = _Stage(descriptor)
    token = _STAGES.set({**(_STAGES.get() or {}), os.path.abspath(path): stage})
    try:
        yield
    finally:
        with stage.lock:
            stage.active = False
            outstanding = stage.leases
        _STAGES.reset(token)
        if outstanding:
            raise MCPVideoError("Staging writer is still active; refusing publication", code="unsafe_path")


@contextlib.contextmanager
def open_staged_writer(path: str):
    """Write only the inode created by the current publication transaction."""
    stage = (_STAGES.get() or {}).get(os.path.abspath(path))
    if stage is None:
        raise MCPVideoError("Writer requires an owned staging file", code="unsafe_path")
    descriptor = stage.duplicate()
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.seek(0)
            stream.truncate()
            yield stream
    finally:
        stage.release(descriptor)


@contextlib.contextmanager
def staged_ffmpeg_command(cmd: list[str], pass_fds: tuple[int, ...] = ()):
    """Hold an independent descriptor lease throughout an owned process call."""
    stage = (_STAGES.get() or {}).get(os.path.abspath(cmd[-1])) if cmd else None
    if stage is None:
        yield cmd, pass_fds
        return
    descriptor = stage.duplicate()
    try:
        yield _rewrite_command(cmd, pass_fds, descriptor)
    finally:
        stage.release(descriptor)


def _rewrite_command(cmd, pass_fds, descriptor):
    """Rewrite only a registered final FFmpeg output; never infer transactions."""
    if os.name != "posix":
        return cmd, pass_fds
    prefix = next((path for path in ("/proc/self/fd", "/dev/fd") if os.path.isdir(path)), None)
    if prefix is None:
        raise MCPVideoError("Descriptor-backed FFmpeg outputs are unavailable", code="unsafe_path")
    suffix = os.path.splitext(cmd[-1])[1].lower()
    output_start = max((i + 2 for i, value in enumerate(cmd[:-1]) if value == "-i"), default=1)
    options = cmd[output_start:-1]
    additions = []
    if "-f" not in options:
        muxer = _MUXERS.get(suffix)
        if muxer is None:
            raise MCPVideoError("Unknown staging output format", code="invalid_output_path")
        additions.extend(["-f", muxer])
    explicit_formats = [options[index + 1] for index, value in enumerate(options[:-1]) if value == "-f"]
    defaults = []
    if suffix in _IMAGE_CODECS and (not explicit_formats or explicit_formats[-1] in {"image2", "image2pipe"}):
        defaults = ["-c:v", _IMAGE_CODECS[suffix]]
    # Earlier defaults preserve every FFmpeg selector's native last-match precedence.
    rewritten = [*cmd[:output_start], *defaults, *cmd[output_start:-1], *additions, f"{prefix}/{descriptor}"]
    return rewritten, tuple(dict.fromkeys((*pass_fds, descriptor)))
