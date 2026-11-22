"""Recovery hints must pin the version that is actually running.

Audit row 78: the missing-Whisper recovery recommended a hardcoded release,
so a user on a newer release who followed the hint downgraded the running
package. Every test here fails against any hardcoded version: they force a
sentinel version through the hint builder and require the recovery
surfaces to interpolate it. The sentinel deliberately matches no release
that has ever shipped, including 1.16.5 and 2.0.1.
"""

from __future__ import annotations

import importlib
import re
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from kinocut import _install_hints
from kinocut.errors import MCPVideoError

SENTINEL_VERSION = "9.9.9-rc1"
EXPECTED_HINT = f'pip install "kinocut[transcribe]=={SENTINEL_VERSION}"'

ROOT = Path(__file__).resolve().parents[1]


def _force_running_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_install_hints, "running_version", lambda: SENTINEL_VERSION)


def _break_whisper_import(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "whisper":
            raise ImportError("No module named 'whisper'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)


class TestHintBuilders:
    def test_running_version_reads_distribution_metadata(self, monkeypatch):
        monkeypatch.setattr(_install_hints, "_distribution_version", lambda name: "3.2.1")
        assert _install_hints.running_version() == "3.2.1"

    def test_running_version_falls_back_to_the_package_constant(self, monkeypatch):
        def missing(name):
            raise _install_hints.PackageNotFoundError(name)

        monkeypatch.setattr(_install_hints, "_distribution_version", missing)
        import kinocut

        assert _install_hints.running_version() == kinocut.__version__

    def test_pip_install_hint_quotes_extras_and_pins_the_running_version(self, monkeypatch):
        _force_running_version(monkeypatch)
        assert _install_hints.pip_install_hint("transcribe") == EXPECTED_HINT

    def test_pip_install_hint_keeps_the_bare_package_unquoted(self, monkeypatch):
        _force_running_version(monkeypatch)
        assert _install_hints.pip_install_hint(quoted=False) == f"pip install kinocut=={SENTINEL_VERSION}"
        # The default spelling keeps the quotes doctor never used for the
        # bare package only because those call sites pass quoted=False.
        assert _install_hints.pip_install_hint() == f'pip install "kinocut=={SENTINEL_VERSION}"'


class TestWhisperRecoveryInterpolatesTheRunningVersion:
    def test_transcribe_error_message_and_suggested_action(self, monkeypatch):
        _force_running_version(monkeypatch)
        _break_whisper_import(monkeypatch)

        from kinocut.ai_engine.transcribe import ai_transcribe

        with pytest.raises(MCPVideoError) as exc_info:
            ai_transcribe("video.mp4")

        err = exc_info.value
        assert err.code == "missing_whisper"
        message = str(err)
        suggested = (err.suggested_action or {}).get("description", "")
        assert EXPECTED_HINT in message
        assert EXPECTED_HINT in suggested
        assert "kinocut[transcribe]" in message  # the extra stays visible
        # No hardcoded release can satisfy a sentinel that matches no
        # shipped release: 1.16.5 (audit row 78) and 2.0.1 alike fail here.
        assert "1.16.5" not in message
        assert "==2.0.1" not in message

    def test_longform_chunk_error_message_and_suggested_action(self, monkeypatch, tmp_path):
        _force_running_version(monkeypatch)
        _break_whisper_import(monkeypatch)

        from kinocut.ai_engine import _longform_runtime
        from kinocut.ai_engine._longform_models import LongformChunk

        monkeypatch.setattr(
            _longform_runtime,
            "_extract_audio_segment",
            lambda *args, **kwargs: str(tmp_path / "chunk.wav"),
        )
        chunk = LongformChunk(index=0, start=0.0, end=1.0, duration=1.0)

        with pytest.raises(MCPVideoError) as exc_info:
            _longform_runtime._transcribe_chunk("video.mp4", chunk, model="tiny", language=None, work_dir=str(tmp_path))

        err = exc_info.value
        assert err.code == "missing_whisper"
        assert EXPECTED_HINT in str(err)
        assert EXPECTED_HINT in (err.suggested_action or {}).get("description", "")


class TestDoctorHintsInterpolateTheRunningVersion:
    def test_package_recovery_hints(self, monkeypatch):
        from kinocut import doctor

        _force_running_version(monkeypatch)
        try:
            doctor = importlib.reload(doctor)
            report = doctor.run_diagnostics(
                which=lambda name: None,
                version_runner=lambda command: None,
                find_spec=lambda name: None,
                package_version=lambda name: None,
            )
            checks = {check["name"]: check for check in report["checks"]}

            whisper_hint = checks["openai-whisper"]["install_hint"]
            assert f"kinocut[transcribe]=={SENTINEL_VERSION}" in whisper_hint
            assert "==2.0.1" not in whisper_hint
            assert f"kinocut[stems]=={SENTINEL_VERSION}" in checks["demucs"]["install_hint"]
            assert f"kinocut[upscale]=={SENTINEL_VERSION}" in checks["realesrgan"]["install_hint"]
            assert f"kinocut[image]=={SENTINEL_VERSION}" in checks["pillow"]["install_hint"]
            assert f"kinocut=={SENTINEL_VERSION}" in checks["mcp-video"]["install_hint"]
        finally:
            monkeypatch.undo()
            importlib.reload(doctor)


class TestRenderedPanel:
    def test_missing_whisper_hint_renders_the_running_version(self, monkeypatch):
        """The rendered panel (not just the exception) must carry the pin.

        Issue #9's renderer bug swallowed the extras token; that fix must
        keep working on top of an interpolated version.
        """
        _force_running_version(monkeypatch)
        _break_whisper_import(monkeypatch)

        from kinocut.ai_engine.transcribe import ai_transcribe
        from kinocut.cli import formatting
        from kinocut.cli.formatting import _format_error

        with pytest.raises(MCPVideoError) as exc_info:
            ai_transcribe("video.mp4")

        output = StringIO()
        captured = Console(file=output, force_terminal=False, color_system=None, width=400)
        with patch.object(formatting, "err_console", captured):
            _format_error(exc_info.value, command="video-ai-transcribe", arguments={"input": "video.mp4"})
        rendered = output.getvalue()

        assert f"kinocut[transcribe]=={SENTINEL_VERSION}" in rendered
        assert 'pip install "kinocut[transcribe]' in rendered
        assert "kino kino" not in rendered
        assert "1.16.5" not in rendered
        assert "==2.0.1" not in rendered


HARDCODED_PIN = re.compile(r"kinocut(?:\[[a-z0-9,-]+\])?==\d")
RECOVERY_SURFACES = (
    "doctor.py",
    "ai_engine/transcribe.py",
    "ai_engine/_longform_runtime.py",
    "_install_hints.py",
)


@pytest.mark.parametrize("relative", RECOVERY_SURFACES)
def test_recovery_surfaces_carry_no_hardcoded_version_pin(relative):
    """Any literal version pin in a recovery surface regresses row 78.

    The interpolated hint makes a stale pin impossible to express; this
    scan keeps it that way for every future release, not just the current
    one.
    """
    text = (ROOT / "kinocut" / relative).read_text(encoding="utf-8")
    match = HARDCODED_PIN.search(text)
    assert match is None, f"{relative} hardcodes a version pin: {match.group(0)!r}"
