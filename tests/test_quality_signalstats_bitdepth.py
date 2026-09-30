"""Real lossless SDR fixtures compare signal domains across depth and range."""

import json
import shutil
import struct
import subprocess

import pytest

from kinocut.quality_guardrails import VisualQualityGuardrails, _normalized_signalstat
from kinocut.errors import MCPVideoError


pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg/FFprobe required",
)


def _fixture_video(root, base, depth, color_range, moving=True):
    width, height = 32, 24
    values = []
    for frame in range(4):
        values.extend(
            40 + x * 150 // (width - 1) + (frame * 2 if moving else 0) for _ in range(height) for x in range(width)
        )
        if base != "gray":
            chroma_width = width // 2 if base in {"yuv420p", "yuv422p"} else width
            chroma_height = height // 2 if base == "yuv420p" else height
            values.extend(110 + x * 30 // (chroma_width - 1) for _ in range(chroma_height) for x in range(chroma_width))
            values.extend(
                140 - y * 30 // (chroma_height - 1) for y in range(chroma_height) for _ in range(chroma_width)
            )
    # Limited YUV code values scale by bit shift. Full-range luma instead uses
    # the actual maximum; chroma is centered at the native neutral code value.
    if depth > 8:
        plane_size = width * height
        chroma_size = 0 if base == "gray" else chroma_width * chroma_height
        frame_size = plane_size + 2 * chroma_size
        values = (
            [
                round(value * ((2**depth) - 1) / 255)
                if index % frame_size < plane_size
                else round((2 ** (depth - 1)) + (value - 128) * ((2**depth) - 1) / 255)
                for index, value in enumerate(values)
            ]
            if color_range == "pc" or base == "gray"
            else [value << (depth - 8) for value in values]
        )
    pixel_format = base if depth == 8 else f"{base}{depth}le"
    raw = root / f"{base}-{depth}-{color_range}-{moving}.raw"
    raw.write_bytes(bytes(values) if depth == 8 else struct.pack(f"<{len(values)}H", *values))
    output = raw.with_suffix(".mkv")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            pixel_format,
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            "4",
            "-color_range",
            color_range,
            "-i",
            str(raw),
            "-c:v",
            "ffv1",
            "-pix_fmt",
            pixel_format,
            "-color_range",
            color_range,
            str(output),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return str(output)


@pytest.fixture(scope="module")
def ramps(tmp_path_factory):
    root = tmp_path_factory.mktemp("quality-bitdepth")
    return {
        (base, depth, color_range): _fixture_video(root, base, depth, color_range)
        for base in ("gray", "yuv420p", "yuv422p", "yuv444p")
        for depth in (8, 10, 12, 16)
        for color_range in ("tv", "pc")
    }


@pytest.mark.parametrize("base", ["gray", "yuv420p", "yuv422p", "yuv444p"])
@pytest.mark.parametrize("color_range", ["tv", "pc"])
def test_equivalent_ramps_share_limited_8bit_measurements(ramps, base, color_range):
    reports = []
    for depth in (8, 10, 12, 16):
        guardrails = VisualQualityGuardrails()
        source = ramps[base, depth, color_range]
        stats = guardrails._get_all_signalstats(source)
        assert stats, "Real signalstats must run; empty fallbacks cannot validate equivalence"
        reports.append(stats)
        assert guardrails.check_brightness(source).passed
        assert "blown highlights" not in guardrails.check_brightness(source).message
        individual = guardrails._run_ffprobe(source, "lavfi.signalstats.YAVG")
        assert individual["mean"] == pytest.approx(stats["lavfi.signalstats.YAVG"], abs=0.001)
        fallback = guardrails._run_ffmpeg_signalstats(source)
        assert fallback["yavg"] == pytest.approx(stats["lavfi.signalstats.YAVG"], abs=0.6)
    for stats in reports[1:]:
        for tag in reports[0]:
            # Native signalstats integer magnitude/percentile rounding and
            # gray->YUV conversion can differ by less than one 8-bit code unit.
            assert stats[tag] == pytest.approx(reports[0][tag], abs=1.0), tag


@pytest.mark.parametrize("base", ["yuv420p", "yuv422p", "yuv444p"])
def test_limited_8bit_baseline_preserves_native_chroma_and_sample_values(ramps, base):
    source = ramps[base, 8, "tv"]
    guardrails = VisualQualityGuardrails()
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            guardrails._movie_source(source, "signalstats"),
            "-show_entries",
            f"frame=pix_fmt,color_range:frame_tags={guardrails._SIGNALSTATS_ALL_TAGS}",
            "-of",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    frames = json.loads(result.stdout)["frames"]
    assert {frame["pix_fmt"] for frame in frames} == {base}
    assert {frame["color_range"] for frame in frames} == {"tv"}
    reference = {tag: sum(float(frame["tags"][tag]) for frame in frames) / len(frames) for tag in frames[0]["tags"]}
    assert guardrails._get_all_signalstats(source) == reference
    rgb = guardrails._get_rgb_means(source)
    assert rgb and all(0 <= rgb[channel] <= 255 for channel in ("r", "g", "b"))


@pytest.mark.parametrize("depth", [8, 10, 12, 16])
def test_grayscale_motion_uses_amplitude_without_limited_black_offset(tmp_path, ramps, depth):
    frozen = _fixture_video(tmp_path, "gray", depth, "pc", moving=False)
    guardrails = VisualQualityGuardrails()
    still = guardrails._measure_temporal_motion(frozen)
    assert still["mean"] == pytest.approx(0.0, abs=0.01)
    assert still["static_fraction"] == 1.0
    motion = guardrails._measure_temporal_motion(ramps["gray", depth, "pc"])
    assert motion["mean"] == pytest.approx(2 * 219 / 255, abs=0.2)
    assert motion["static_fraction"] == 0.0


def test_range_metadata_and_unknown_assumption_are_explicit(monkeypatch):
    assert _normalized_signalstat({"pix_fmt": "yuv420p10le", "color_range": "tv"}, "YAVG", 512) == 128
    assert _normalized_signalstat({"pix_fmt": "yuv420p10le", "color_range": "pc"}, "YAVG", 1023) == 235
    assert _normalized_signalstat({"pix_fmt": "yuvj444p"}, "YAVG", 255) == 235
    assert _normalized_signalstat({}, "YAVG", 128) == 128
    assert _normalized_signalstat({"pix_fmt": "yuvj444p"}, "YAVG", 0, difference=True) == 0
    guardrails = VisualQualityGuardrails()
    monkeypatch.setattr(guardrails, "run_all_checks", lambda source: [])
    domain = guardrails.generate_report("synthetic")["analysis_domain"]
    assert domain["transfer_conversion"] == "none"
    assert "HDR_delivery_acceptance_not_evaluated" in domain["applicability"]
    assert "limited_assumed" in domain["input_range"]


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_probe_values_are_unusable(value, monkeypatch):
    result = subprocess.CompletedProcess(
        [],
        0,
        json.dumps(
            {
                "frames": [
                    {"pix_fmt": "yuv420p", "tags": {"lavfi.signalstats.YAVG": value}},
                ]
            }
        ),
        "",
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: result)
    guardrails = VisualQualityGuardrails()
    assert guardrails._get_all_signalstats("invalid") == {}
    assert "_error" in guardrails._run_ffprobe("invalid", "lavfi.signalstats.YAVG")
    assert "_error" in guardrails._measure_temporal_motion("invalid")


def test_invalid_depth_is_unusable():
    with pytest.raises(MCPVideoError):
        _normalized_signalstat({"pix_fmt": "yuv420p32le"}, "YAVG", 128)


def test_real_hdr_transfer_metadata_emits_scope_warning(ramps, monkeypatch, caplog):
    guardrails = VisualQualityGuardrails()
    movie_source = guardrails._movie_source
    # Stamp decoded frames: these SDR sample values do not simulate HDR
    # content, but FFprobe must surface the transfer metadata from real frames.
    monkeypatch.setattr(
        guardrails, "_movie_source", lambda source, tail: movie_source(source, f"setparams=color_trc=smpte2084,{tail}")
    )
    assert guardrails._get_all_signalstats(ramps["yuv420p", 10, "tv"])
    assert caplog.text.count("HDR transfer observed") == 1
    assert "do not evaluate HDR delivery acceptance" in caplog.text
