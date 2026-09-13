"""Cached models and launchers cannot silently select downloads or shell execution."""

import hashlib
from pathlib import Path
import sys
import time

import pytest

from kinocut_sound._errors import SoundContractError
from kinocut_sound.public import asr_runtime
from kinocut_sound.public.asr_request import AsrError


@pytest.mark.parametrize("kind", ["missing", "digest", "symlink", "oversized"])
def test_cached_checkpoint_failures(tmp_path, monkeypatch, kind):
    cache = tmp_path / ".cache/whisper"
    cache.mkdir(parents=True)
    model = cache / "base.pt"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if kind == "symlink":
        target = tmp_path / "outside.pt"
        target.write_bytes(b"data")
        model.symlink_to(target)
    elif kind == "oversized":
        with model.open("wb") as output:
            output.truncate(asr_runtime.MAX_ASR_MODEL_BYTES + 1)
    elif kind == "digest":
        model.write_bytes(b"wrong")
    with pytest.raises(SoundContractError):
        asr_runtime.copy_checkpoint("base", "0" * 64, tmp_path / "staged.pt", time.monotonic() + 10)


def test_checkpoint_is_copied_and_hashed_without_importing_backend(tmp_path, monkeypatch):
    cache = tmp_path / ".cache/whisper"
    cache.mkdir(parents=True)
    data = b"fixed test checkpoint"
    (cache / "base.pt").write_bytes(data)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    output = tmp_path / "stage.pt"
    assert asr_runtime.copy_checkpoint("base", hashlib.sha256(data).hexdigest(), output, time.monotonic() + 10) == len(
        data
    )
    assert output.read_bytes() == data


@pytest.mark.parametrize("shebang", ["#!/usr/bin/env python", "#!/bin/sh", "#!/python -c", "not a launcher"])
def test_launcher_rejects_shell_env_and_arguments(tmp_path, monkeypatch, shebang):
    launcher = tmp_path / "whisper"
    launcher.write_text(shebang + "\n")
    monkeypatch.setattr(asr_runtime.shutil, "which", lambda _: str(launcher))
    runtimes = asr_runtime.interpreters()
    assert next(runtimes) == str(Path(sys.executable).absolute())
    with pytest.raises(AsrError):
        next(runtimes)


def test_launcher_preserves_virtual_environment_entry(tmp_path, monkeypatch):
    entry = tmp_path / "python"
    entry.symlink_to(Path(sys.executable).resolve())
    launcher = tmp_path / "whisper"
    launcher.write_text("#!" + str(entry) + "\n")
    monkeypatch.setattr(asr_runtime.shutil, "which", lambda _: str(launcher))
    assert list(asr_runtime.interpreters())[-1] == str(entry)
