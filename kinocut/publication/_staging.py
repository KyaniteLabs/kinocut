"""Context-owned staging descriptors shared by publication and process runners."""

from __future__ import annotations

import contextlib
import os
import re
import sys
import threading
from contextvars import ContextVar

from ..errors import MCPVideoError


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
    ".bmp": "image2",
    ".tif": "image2",
    ".tiff": "image2",
    ".webp": "webp",
}
_IMAGE_CODECS = {
    ".png": "png",
    ".jpg": "mjpeg",
    ".jpeg": "mjpeg",
    ".bmp": "bmp",
    ".tif": "tiff",
    ".tiff": "tiff",
    ".webp": "webp",
}


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
        prepared, faststart = _darwin_faststart_command(cmd)
        yield _rewrite_command(prepared, pass_fds, descriptor)
        if faststart:
            from ..mp4_faststart import relocate_index

            relocate_index(descriptor)
    finally:
        stage.release(descriptor)


_FFMPEG_VALUE_FLAGS = frozenset(
    {
        "-f",
        "-ss",
        "-t",
        "-to",
        "-r",
        "-s",
        "-c",
        "-c:v",
        "-c:a",
        "-c:s",
        "-vcodec",
        "-acodec",
        "-vf",
        "-af",
        "-filter:v",
        "-filter:a",
        "-filter_complex",
        "-map",
        "-metadata",
        "-b:v",
        "-b:a",
        "-ar",
        "-ac",
        "-pix_fmt",
        "-preset",
        "-crf",
        "-movflags",
        "-v",
        "-loglevel",
        "-threads",
        "-loop",
        "-stream_loop",
        "-itsoffset",
        "-frames:v",
        "-vframes",
        "-q:v",
        "-q:a",
        "-protocol_whitelist",
    }
)


def _find_output_start(cmd: list[str]) -> int:
    """Locate the index right after the last real ``-i <input>`` pair without misreading option values."""
    output_start = 1
    index = 1
    end = len(cmd) - 1
    while index < end:
        arg = cmd[index]
        if arg == "-i":
            output_start = min(index + 2, end)
            index += 2
            continue
        if arg in _FFMPEG_VALUE_FLAGS or arg.startswith(("-metadata:", "-c:", "-b:", "-filter:", "-map_metadata")):
            index += 2
            continue
        index += 1
    return output_start


def _darwin_faststart_command(cmd: list[str]) -> tuple[list[str], bool]:
    if sys.platform != "darwin":
        return cmd, False
    output_start = _find_output_start(cmd)
    enabled = False
    for index in range(output_start, len(cmd) - 2):
        if cmd[index] == "-movflags":
            value = cmd[index + 1]
            if not value.startswith(("+", "-")):
                enabled = False  # An unsigned flags value replaces earlier settings.
            for token in re.finditer(r"(?:^|[+-])faststart(?=$|[+-])", value):
                enabled = not token.group().startswith("-")
    if not enabled:
        return cmd, False
    # /dev/fd reopens share an offset on Darwin; FFmpeg's shifting pass needs
    # independent reader/writer offsets. Relocate through pread/pwrite instead.
    return [*cmd[:-1], "-movflags", "-faststart", cmd[-1]], True


def _rewrite_command(cmd, pass_fds, descriptor):
    """Rewrite only a registered final FFmpeg output; never infer transactions."""
    if os.name != "posix":
        return cmd, pass_fds
    prefix = next((path for path in ("/proc/self/fd", "/dev/fd") if os.path.isdir(path)), None)
    if prefix is None:
        raise MCPVideoError("Descriptor-backed FFmpeg outputs are unavailable", code="unsafe_path")
    suffix = os.path.splitext(cmd[-1])[1].lower()
    output_start = _find_output_start(cmd)
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
