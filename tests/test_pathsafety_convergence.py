"""Regression tests: ai_engine entry points reject the same hostile output paths
as the canonical _validate_output_path in ffmpeg_helpers.py.

Test strategy:
1. Verify the canonical validator covers all paths the old AI-engine validator
   covered (plus the new ones added to fill gaps).
2. Verify _validate_analysis_output_paths now delegates to the canonical validator.
3. Verify each ai_engine public entry-point that validates an output path uses
   the canonical validator (wiring test — monkeypatch the canonical validator
   and confirm the module calls it).
"""

from __future__ import annotations

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.ffmpeg_helpers import _validate_output_path

# All error codes the canonical validator can emit
_VALID_ERROR_CODES = {"unsafe_path", "validation_error", "invalid_output_path"}

# Paths that must be blocked on any OS — these are either absolute system paths
# or paths with traversal sequences.
_HOSTILE_OUTPUTS = [
    "/etc/passwd.mp4",
    "/etc/cron.d/evil.mp4",
    "/usr/bin/output.mp4",
    "/usr/local/lib/output.mp4",
    "/bin/sh.mp4",
    "/sbin/output.mp4",
    "/root/evil.mp4",
    "/boot/grub/evil.mp4",
    "/dev/null",
    "/proc/self/mem",
    "/sys/kernel/evil",
    # macOS /private/* symlink targets for /etc
    "/private/etc/evil.mp4",
    # Targeted /var sub-paths that must be blocked
    "/var/db/evil.mp4",
    "/var/root/evil.mp4",
]


# ---------------------------------------------------------------------------
# Canonical validator — baseline
# ---------------------------------------------------------------------------


class TestCanonicalValidator:
    @pytest.mark.parametrize("path", _HOSTILE_OUTPUTS)
    def test_blocks_hostile_paths(self, path: str) -> None:
        with pytest.raises(MCPVideoError) as exc_info:
            _validate_output_path(path)
        assert exc_info.value.code in _VALID_ERROR_CODES

    def test_blocks_traversal(self) -> None:
        with pytest.raises(MCPVideoError) as exc_info:
            _validate_output_path("/tmp/../etc/passwd")
        assert exc_info.value.code in _VALID_ERROR_CODES

    def test_blocks_null_bytes(self) -> None:
        with pytest.raises(MCPVideoError) as exc_info:
            _validate_output_path("/tmp/out\x00put.mp4")
        assert exc_info.value.code in _VALID_ERROR_CODES

    def test_allows_tmp(self) -> None:
        # /tmp is not blocked — should not raise
        assert _validate_output_path("/tmp/output.mp4") == "/tmp/output.mp4"

    def test_allows_relative(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert _validate_output_path("relative/output.mp4") == "relative/output.mp4"

    def test_blocks_sensitive_home_ssh(self, tmp_path, monkeypatch) -> None:
        """Writes targeting ~/.ssh are rejected."""
        import os

        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        ssh_dir = fake_home / ".ssh"
        ssh_dir.mkdir()
        # Patch expanduser so the validator sees our fake home
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(fake_home) if p == "~" else p)
        with pytest.raises(MCPVideoError) as exc_info:
            _validate_output_path(str(ssh_dir / "authorized_keys"))
        assert exc_info.value.code in _VALID_ERROR_CODES


# ---------------------------------------------------------------------------
# _validate_analysis_output_paths — delegates to canonical validator
# ---------------------------------------------------------------------------


class TestAnalysisOutputPathsDelegation:
    """_validate_analysis_output_paths must reject the same hostile paths."""

    @pytest.mark.parametrize("path", _HOSTILE_OUTPUTS)
    def test_blocks_hostile_paths(self, path: str) -> None:
        from mcp_video.ai_engine import _validate_analysis_output_paths

        with pytest.raises(MCPVideoError) as exc_info:
            _validate_analysis_output_paths(output_srt=path, output_txt=None, output_md=None, output_json=None)
        assert exc_info.value.code in _VALID_ERROR_CODES

    def test_blocks_traversal(self) -> None:
        from mcp_video.ai_engine import _validate_analysis_output_paths

        with pytest.raises(MCPVideoError):
            _validate_analysis_output_paths(
                output_srt=None,
                output_txt="/tmp/../etc/shadow.txt",
                output_md=None,
                output_json=None,
            )

    def test_allows_tmp_paths(self) -> None:
        from mcp_video.ai_engine import _validate_analysis_output_paths

        _validate_analysis_output_paths(
            output_srt="/tmp/transcript.srt",
            output_txt=None,
            output_md=None,
            output_json=None,
        )

        with pytest.raises(MCPVideoError):
            _validate_analysis_output_paths("/tmp/../etc/transcript.srt", None, None, None)

    def test_allows_relative_paths(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        from mcp_video.ai_engine import _validate_analysis_output_paths

        _validate_analysis_output_paths(
            output_srt=None,
            output_txt=None,
            output_md="relative/path.md",
            output_json=None,
        )
        with pytest.raises(MCPVideoError):
            _validate_analysis_output_paths(None, None, "../../etc/path.md", None)

    def test_checks_each_parameter(self) -> None:
        """Every non-None parameter is validated independently."""
        from mcp_video.ai_engine import _validate_analysis_output_paths

        hostile = "/etc/evil"
        for kwarg in ("output_srt", "output_txt", "output_md", "output_json"):
            kwargs = {"output_srt": None, "output_txt": None, "output_md": None, "output_json": None}
            kwargs[kwarg] = hostile
            with pytest.raises(MCPVideoError) as exc_info:
                _validate_analysis_output_paths(**kwargs)
            assert exc_info.value.code in _VALID_ERROR_CODES, f"Expected MCPVideoError for {kwarg}={hostile!r}"


# ---------------------------------------------------------------------------
# Wiring tests — confirm each ai_engine module calls _validate_output_path
# from ffmpeg_helpers (not an ad-hoc copy)
# ---------------------------------------------------------------------------


class TestValidatorImportWiring:
    """Each ai_engine module that validates output paths imports and calls the
    canonical _validate_output_path from ffmpeg_helpers.  We patch it at the
    ffmpeg_helpers level and confirm the module's public entry point calls it."""

    def _patch_validate_output(self, monkeypatch, module_path: str):
        """Monkeypatch _validate_output_path in the named module and return a recorder."""
        import importlib

        mod = importlib.import_module(module_path)
        calls: list[str] = []

        def recording_validator(path: str) -> str:
            calls.append(path)
            raise MCPVideoError(f"blocked: {path}", error_type="validation_error", code="unsafe_path")

        monkeypatch.setattr(mod, "_validate_output_path", recording_validator)
        return calls

    def test_upscale_calls_canonical_validator(self, tmp_path, monkeypatch) -> None:
        import mcp_video.ai_engine.upscale as _upscale_mod

        calls = self._patch_validate_output(monkeypatch, "mcp_video.ai_engine.upscale")
        monkeypatch.setattr(_upscale_mod, "_validate_input_path", lambda p: p)
        # Patch resource limit check so we reach _validate_output_path
        monkeypatch.setattr(_upscale_mod, "_validate_upscale_resource_limits", lambda p: None)

        # Create a real file so the Path.exists() guard passes
        fake_input = tmp_path / "fake.mp4"
        fake_input.write_bytes(b"\x00")

        with pytest.raises(MCPVideoError, match="blocked"):
            _upscale_mod.ai_upscale(str(fake_input), "/etc/out.mp4")
        assert len(calls) >= 1
        assert "/etc/out.mp4" in calls

    def test_silence_calls_canonical_validator(self, tmp_path, monkeypatch) -> None:
        import mcp_video.ai_engine.silence as _silence_mod

        calls = self._patch_validate_output(monkeypatch, "mcp_video.ai_engine.silence")
        monkeypatch.setattr(_silence_mod, "_validate_input_path", lambda p: p)

        # Create a real file so the Path.exists() guard passes
        fake_input = tmp_path / "fake.mp4"
        fake_input.write_bytes(b"\x00")

        with pytest.raises(MCPVideoError, match="blocked"):
            _silence_mod.ai_remove_silence(str(fake_input), "/etc/out.mp4")
        assert len(calls) >= 1
        assert "/etc/out.mp4" in calls

    def test_spatial_calls_canonical_validator(self, tmp_path, monkeypatch) -> None:
        import mcp_video.ai_engine.spatial as _spatial_mod

        calls = self._patch_validate_output(monkeypatch, "mcp_video.ai_engine.spatial")
        monkeypatch.setattr(_spatial_mod, "_validate_input_path", lambda p: p)
        monkeypatch.setattr(_spatial_mod, "_require_audio_stream", lambda p: None)

        # Create a real file so the Path.exists() guard passes
        fake_input = tmp_path / "fake.mp4"
        fake_input.write_bytes(b"\x00")

        with pytest.raises(MCPVideoError, match="blocked"):
            _spatial_mod.audio_spatial(
                str(fake_input),
                "/etc/out.mp4",
                positions=[{"time": 0, "azimuth": 0, "elevation": 0}],
            )
        assert len(calls) >= 1
        assert "/etc/out.mp4" in calls

    def test_stem_calls_canonical_validator(self, tmp_path, monkeypatch) -> None:
        """ai_stem_separation calls _validate_output_path on the output directory."""
        import mcp_video.ai_engine.stem as _stem_mod

        calls = self._patch_validate_output(monkeypatch, "mcp_video.ai_engine.stem")
        monkeypatch.setattr(_stem_mod, "_validate_input_path", lambda p: p)
        monkeypatch.setattr(_stem_mod, "_validate_stem_duration", lambda p: None)
        # Patch the demucs import check so we pass the dep guard
        monkeypatch.setattr(
            _stem_mod, "importlib", type("_FakeImportlib", (), {"import_module": staticmethod(lambda name: None)})()
        )

        # Create a real file so the Path.exists() check passes
        fake_input = tmp_path / "fake.wav"
        fake_input.write_bytes(b"RIFF")

        with pytest.raises(MCPVideoError, match="blocked"):
            _stem_mod.ai_stem_separation(str(fake_input), "/etc/stems")
        assert len(calls) >= 1
        assert "/etc/stems" in calls

    def test_transcribe_calls_canonical_validator(self, tmp_path, monkeypatch) -> None:
        """ai_transcribe calls _validate_output_path on output_srt."""
        # transcribe validates output_srt INSIDE the try block after whisper loads.
        # We test the import wiring: _validate_output_path comes from ffmpeg_helpers.
        import mcp_video.ai_engine.transcribe as _transcribe_mod

        assert hasattr(_transcribe_mod, "_validate_output_path"), (
            "_validate_output_path must be imported in transcribe module"
        )
        assert _transcribe_mod._validate_output_path is _validate_output_path, (
            "transcribe._validate_output_path must be the canonical one from ffmpeg_helpers"
        )
