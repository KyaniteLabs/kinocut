"""Linux default font falls back to fontconfig when DejaVu is absent (#696)."""

from __future__ import annotations

import subprocess

import pytest

from kinocut import engine_runtime_utils as eru
from kinocut.errors import MCPVideoError


@pytest.fixture
def linux_without_dejavu(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    real_isfile = eru.os.path.isfile
    monkeypatch.setattr(eru.os.path, "isfile", lambda p: "DejaVu" not in str(p) and real_isfile(p))


def _fc_match(monkeypatch, stdout: str, returncode: int = 0):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_falls_back_to_fontconfig_sans(linux_without_dejavu, monkeypatch, tmp_path):
    font = tmp_path / "Inter-Regular.ttf"
    font.write_bytes(b"x")
    calls = _fc_match(monkeypatch, str(font))
    assert eru._default_font() == str(font)
    assert calls == [["fc-match", "--format=%{file}", "sans-serif"]]


def test_rejects_non_scalable_fontconfig_match(linux_without_dejavu, monkeypatch, tmp_path):
    bitmap = tmp_path / "cursor.pcf.gz"
    bitmap.write_bytes(b"x")
    _fc_match(monkeypatch, str(bitmap))
    with pytest.raises(MCPVideoError) as exc:
        eru._default_font()
    assert exc.value.code == "font_not_found"


def test_missing_fc_match_still_raises_font_not_found(linux_without_dejavu, monkeypatch):
    def run(*_a, **_k):
        raise FileNotFoundError("fc-match")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(MCPVideoError) as exc:
        eru._default_font()
    assert exc.value.code == "font_not_found"


def test_dejavu_still_preferred_when_present(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    target = "/usr/share/fonts/TTF/DejaVuSans.ttf"
    monkeypatch.setattr(eru.os.path, "isfile", lambda p: p == target)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("fontconfig consulted before DejaVu"))
    assert eru._default_font() == target
