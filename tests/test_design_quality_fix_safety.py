"""Real writers must preserve destinations and use the active guardrail MRO."""

import shutil

import pytest

from kinocut.design_quality.guardrails import DesignQualityGuardrails
from kinocut.design_quality.guardrails.fixes import FixesMixin
from kinocut.errors import InputFileError, MCPVideoError, ProcessingError
from kinocut.ffmpeg_helpers import _run_ffprobe_json

FIXES = (
    "_auto_fix_brightness",
    "_auto_fix_contrast",
    "_auto_fix_saturation",
    "_auto_fix_color_cast",
    "_auto_normalize_audio",
)


@pytest.fixture
def source(sample_video, tmp_path):
    path = tmp_path / "source.mp4"
    shutil.copyfile(sample_video, path)
    return path


@pytest.mark.parametrize("method", FIXES)
def test_real_fix_publishes_decodable_media_through_canonical_mro(source, method):
    guardrail = DesignQualityGuardrails()
    assert getattr(DesignQualityGuardrails, method) is getattr(FixesMixin, method)
    result = getattr(guardrail, method)(str(source))
    assert result == str(source.with_name("source_fixed.mp4"))
    streams = _run_ffprobe_json(result)["streams"]
    assert any(stream["codec_type"] == "video" for stream in streams)
    assert any(stream["codec_type"] == "audio" for stream in streams)
    assert not list(source.parent.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("method", FIXES)
def test_preexisting_output_symlink_does_not_overwrite_unrelated_file(source, method):
    unrelated = source.with_name("unrelated.mp4")
    unrelated.write_bytes(b"preserve unrelated media")
    output = source.with_name("source_fixed.mp4")
    try:
        output.symlink_to(unrelated)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(MCPVideoError) as error:
        getattr(DesignQualityGuardrails(), method)(str(source))
    assert error.value.code == "unsafe_path"
    assert output.is_symlink()
    assert unrelated.read_bytes() == b"preserve unrelated media"
    assert not list(source.parent.glob(".kinocut_tmp_*"))


@pytest.mark.parametrize("method", FIXES)
def test_real_decoder_failure_keeps_existing_destination_and_cleans_stage(tmp_path, method):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"not a video")
    output = tmp_path / "source_fixed.mp4"
    output.write_bytes(b"keep previous artifact")
    with pytest.raises(InputFileError):
        getattr(DesignQualityGuardrails(), method)(str(source))
    assert output.read_bytes() == b"keep previous artifact"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


def test_real_saturation_filter_error_keeps_existing_destination(source):
    output = source.with_name("source_fixed.mp4")
    output.write_bytes(b"keep previous artifact")
    with pytest.raises(ProcessingError):
        DesignQualityGuardrails()._auto_fix_saturation(str(source), boost="not_a_number")
    assert output.read_bytes() == b"keep previous artifact"
    assert not list(source.parent.glob(".kinocut_tmp_*"))
