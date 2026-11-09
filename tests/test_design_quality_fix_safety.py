"""Real writers must preserve destinations and use the active guardrail MRO."""

import shutil

import pytest

from kinocut.design_quality.guardrails import DesignQualityGuardrails
from kinocut.design_quality.guardrails.fixes import FixesMixin
from kinocut.errors import InputFileError, MCPVideoError, ProcessingError
from kinocut.ffmpeg_helpers import _run_ffprobe_json

# Replacement transactions explicitly opt in; default denial has separate coverage.
pytestmark = pytest.mark.usefixtures("overwrite_consent")

FIXES = (
    "_auto_fix_brightness",
    "_auto_fix_saturation",
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


def _mean_luma_and_sat(path):
    import subprocess

    out = (
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-f",
                "lavfi",
                f"movie={path},signalstats",
                "-show_entries",
                "frame_tags=lavfi.signalstats.YAVG,lavfi.signalstats.SATAVG",
                "-of",
                "csv=p=0",
                "-read_intervals",
                "%+#1",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .splitlines()[0]
    )
    luma, sat = (float(v) for v in out.split(",")[:2])
    return luma, sat


def test_brightness_and_saturation_fixes_both_reach_output(tmp_path):
    """#686: both fixes must survive; applying them one by one kept only the last."""
    import subprocess

    from kinocut.design_quality.guardrails.fixes import BRIGHTNESS_FILTER, saturation_filter
    from kinocut.design_quality.models import DesignIssue

    source = tmp_path / "dark.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x302820:s=160x90:d=1:r=10",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
    )
    guardrail = DesignQualityGuardrails()
    issues = [
        DesignIssue(
            "typography",
            "warning",
            "dark",
            fix_available=True,
            auto_fix=lambda v: guardrail._auto_fix_brightness(v),
            fix_filter=BRIGHTNESS_FILTER,
        ),
        DesignIssue(
            "color",
            "warning",
            "desaturated",
            fix_available=True,
            auto_fix=lambda v: guardrail._auto_fix_saturation(v),
            fix_filter=saturation_filter(1.2),
        ),
    ]
    applied = guardrail._apply_auto_fixes(str(source), issues)
    assert applied == ["typography: dark", "color: desaturated"]

    base_luma, base_sat = _mean_luma_and_sat(source)
    fixed_luma, fixed_sat = _mean_luma_and_sat(source.with_name("dark_fixed.mp4"))
    assert fixed_luma > base_luma + 10, "brightness fix missing from output"
    assert fixed_sat > base_sat, "saturation fix missing from output"
