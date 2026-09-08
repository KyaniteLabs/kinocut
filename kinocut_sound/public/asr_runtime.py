"""Discover only installed Python/Whisper runtimes and copy verified cached models."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

from kinocut_sound.limits import MAX_ASR_LAUNCHER_BYTES, MAX_ASR_MODEL_BYTES, ASR_COPY_CHUNK_BYTES
from kinocut_sound.public.asr_compare import remaining
from kinocut_sound.public.asr_request import asr_error
from kinocut_sound.public.mix_files import _read_regular_file, open_root
from kinocut_sound.validation import ASR_PYTHON_NAME_RE, ASR_VERSION_RE, ASR_MODEL_DIGEST_RE


def interpreters():
    current = str(Path(sys.executable).absolute())
    yield current
    launcher = shutil.which("whisper")
    if launcher:
        try:
            path = Path(launcher).resolve(strict=True)
            with open_root(str(path.parent)) as root:
                data = _read_regular_file(root, path.name, MAX_ASR_LAUNCHER_BYTES)
            first = data.split(b"\n", 1)[0].decode("utf-8")
            if not first.startswith("#!/") or any(c.isspace() for c in first):
                raise asr_error("unsupported Whisper launcher", "asr_unavailable")
            interpreter = Path(first[2:]).resolve(strict=True)
            if not ASR_PYTHON_NAME_RE.fullmatch(interpreter.name):
                raise asr_error("Whisper launcher must use a Python interpreter", "asr_unavailable")
            if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
                raise asr_error("Whisper interpreter unavailable", "asr_unavailable")
            # Preserve the venv entry path: resolving its symlink before exec
            # would change sys.prefix and silently discard installed packages.
            if first[2:] != current:
                yield first[2:]
        except (OSError, UnicodeError) as exc:
            raise asr_error("Whisper runtime cannot be inspected", "asr_unavailable") from exc


def parse_probe(data):
    try:
        result = json.loads(data)
        if result.get("available") is not True:
            return None
        if set(result) != {"available", "version", "models"} or set(result["models"]) != {"base", "base.en"}:
            raise asr_error("invalid installed ASR registry", "asr_unavailable")
        if not ASR_VERSION_RE.fullmatch(result["version"]):
            raise asr_error("invalid ASR version", "asr_unavailable")
        if any(not ASR_MODEL_DIGEST_RE.fullmatch(value) for value in result["models"].values()):
            raise asr_error("invalid ASR model digest", "asr_unavailable")
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        raise asr_error("invalid ASR runtime probe", "asr_unavailable") from exc


def copy_checkpoint(model, expected, destination, deadline):
    cache = Path.home() / ".cache" / "whisper"
    try:
        with open_root(str(cache)) as root:
            fd = os.open(model + ".pt", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
            with os.fdopen(fd, "rb") as source, destination.open("xb") as output:
                before = os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_ASR_MODEL_BYTES:
                    raise asr_error("cached model exceeds bound", "asr_over_limit")
                digest, size = hashlib.sha256(), 0
                while chunk := source.read(ASR_COPY_CHUNK_BYTES):
                    remaining(deadline)
                    size += len(chunk)
                    if size > MAX_ASR_MODEL_BYTES:
                        raise asr_error("cached model grew during read", "asr_over_limit")
                    digest.update(chunk)
                    output.write(chunk)
                after = os.fstat(source.fileno())
        markers = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in markers) or digest.hexdigest() != expected:
            raise asr_error("cached model identity mismatch", "asr_model_mismatch")
        remaining(deadline)
        return size
    except OSError as exc:
        raise asr_error("verified cached ASR model unavailable", "asr_unavailable") from exc
