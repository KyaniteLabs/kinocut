"""Conversion publishes only after encoding, callbacks and postflight succeed."""

from pathlib import Path
import shutil

import pytest

from kinocut import engine_convert, ffmpeg_helpers
from kinocut.engine_probe import probe
from kinocut.errors import InputFileError, MCPVideoError, ProcessingError


def _destination(tmp_path, sample_video, existing):
    output = tmp_path / "converted.mp4"
    if existing:
        shutil.copyfile(sample_video, output)
    return output, output.read_bytes() if existing else None


def _assert_preserved(output, original):
    if original is None:
        assert not output.exists()
    else:
        assert output.read_bytes() == original
    assert not list(output.parent.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("existing", [False, True])
def test_progress_callback_failure_preserves_destination(sample_video, tmp_path, existing):
    output, original = _destination(tmp_path, sample_video, existing)

    def callback(percent):
        if percent >= 100:
            raise MCPVideoError("callback failed", code="callback_failed")

    with pytest.raises(MCPVideoError, match="callback failed"):
        engine_convert.convert(sample_video, quality="low", output_path=str(output), on_progress=callback)

    _assert_preserved(output, original)


@pytest.mark.parametrize("existing", [False, True])
def test_real_encoding_timeout_preserves_destination(sample_video, tmp_path, monkeypatch, existing):
    output, original = _destination(tmp_path, sample_video, existing)
    run = engine_convert._run_ffmpeg_with_progress

    def realtime(args, estimated_duration, on_progress):
        return run(["-re", *args], estimated_duration, on_progress)

    monkeypatch.setattr(engine_convert, "_run_ffmpeg_with_progress", realtime)
    monkeypatch.setattr(ffmpeg_helpers, "DEFAULT_FFMPEG_TIMEOUT", 0.3)
    with pytest.raises(ProcessingError, match="timed out"):
        engine_convert.convert(sample_video, quality="low", output_path=str(output), on_progress=lambda _: None)

    _assert_preserved(output, original)


@pytest.mark.parametrize("existing", [False, True])
def test_postflight_failure_preserves_destination(sample_video, tmp_path, monkeypatch, existing):
    output, original = _destination(tmp_path, sample_video, existing)
    real_probe = engine_convert.probe
    rendered = []

    def reject_staged(path):
        info = real_probe(path)
        if Path(path).name.startswith(".kinocut_tmp_"):
            assert info.duration > 0 and Path(path).stat().st_size > 0
            rendered.append(path)
            raise InputFileError(path, "injected postflight failure")
        return info

    monkeypatch.setattr(engine_convert, "probe", reject_staged)
    with pytest.raises(InputFileError, match="postflight failure"):
        engine_convert.convert(sample_video, quality="low", output_path=str(output))

    assert len(rendered) == 1
    _assert_preserved(output, original)


@pytest.mark.parametrize("format", ["mp4", "webm", "gif", "mov"])
def test_success_publishes_media_and_returns_public_path(sample_video, tmp_path, format):
    output = tmp_path / f"converted.{format}"
    shutil.copyfile(sample_video, output)
    original = output.read_bytes()
    progress = []
    result = engine_convert.convert(
        sample_video, format=format, quality="low", output_path=str(output), on_progress=progress.append
    )

    assert result.success and result.output_path == str(output)
    assert result.format == format and result.operation == "convert"
    assert result.progress == 100.0 and progress[-1] == 100.0
    assert result.elapsed_ms is not None and result.size_mb is not None
    assert output.read_bytes() != original
    assert probe(str(output)).duration > 0
    if format == "gif":
        assert result.duration is None and result.resolution is None and result.thumbnail_base64 is None
    else:
        assert result.duration > 0 and result.resolution
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("hardlink", [False, True])
def test_conversion_rejects_source_alias_before_staging(sample_video, tmp_path, hardlink):
    source = tmp_path / "source.mp4"
    shutil.copyfile(sample_video, source)
    output = tmp_path / "alias.mp4" if hardlink else source
    if hardlink:
        output.hardlink_to(source)
    original = source.read_bytes()

    with pytest.raises(MCPVideoError, match="aliases an input"):
        engine_convert.convert(str(source), output_path=str(output))

    assert source.read_bytes() == original
    assert not list(tmp_path.glob(".kinocut_tmp_*"))
