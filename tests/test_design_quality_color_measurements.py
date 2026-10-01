"""Design decisions reuse canonical, source-aware clip-average measurements."""

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from kinocut.design_quality.guardrails import DesignQualityGuardrails
from kinocut.design_quality.guardrails.measurements import _quality_engine
from kinocut.quality_guardrails import VisualQualityGuardrails


@pytest.fixture
def color_clip(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")

    def build(color="gray", depth=8, color_range="tv", name="source.mkv"):
        path = tmp_path / name
        pixel_format = "yuv444p" if depth == 8 else f"yuv444p{depth}le"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color={color}:s=32x32:r=4:d=0.5,format={pixel_format}",
                "-vf",
                f"scale=out_range={color_range}",
                "-color_range",
                color_range,
                "-c:v",
                "ffv1",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return str(path)

    return build


@pytest.mark.parametrize("color", ["gray", "red", "blue", "white", "black"])
@pytest.mark.parametrize("depth,color_range", [(8, "tv"), (10, "tv"), (12, "pc")])
def test_design_color_matches_canonical_metrics_and_rgb_bounds(color_clip, color, depth, color_range):
    source = color_clip(color, depth, color_range)
    canonical = VisualQualityGuardrails()
    rgb = canonical._get_rgb_means(source)
    expected_saturation = canonical.check_saturation(source).details["metric"]
    design = DesignQualityGuardrails()
    result = design._analyze_colors(source)
    assert result["rgb_means"] == pytest.approx([rgb[channel] for channel in ("r", "g", "b")])
    assert all(0 <= channel <= 255 for channel in result["rgb_means"])
    assert result["rgb_metric"]["approximate"] is True
    assert result["saturation_metric"] == expected_saturation
    if color in {"gray", "white", "black"}:
        # Canonical high-depth code normalization can shift neutral chroma
        # by sub-code rounding; this is an approximation, not calibrated RGB.
        assert max(result["rgb_means"]) - min(result["rgb_means"]) < 2


def test_all_design_color_consumers_share_one_uncached_analysis(color_clip, monkeypatch):
    source = color_clip()
    design = DesignQualityGuardrails()
    engine = _quality_engine(design)
    original = engine._get_all_signalstats
    uncached_calls = []

    def observe(video):
        key = engine._signalstats_cache_key(video)
        if key not in getattr(engine, "_signalstats_cache", {}):
            uncached_calls.append(video)
        return original(video)

    monkeypatch.setattr(engine, "_get_all_signalstats", observe)
    design._analyze_colors(source)
    assert design._get_mean_luma(source) is not None
    assert design._get_contrast(source) is not None
    design._check_color(source)
    design._check_typography(source)
    assert uncached_calls == [source]


def test_returned_metrics_cannot_mutate_design_cache(color_clip):
    source = color_clip("red")
    design = DesignQualityGuardrails()
    initial = design._analyze_colors(source)
    expected = initial["rgb_means"].copy()
    initial["rgb_means"][0] = -999
    initial["saturation_metric"]["available"] = False
    initial["rgb_metric"]["value"][0] = -999
    design.metrics["rgb"]["value"][0] = -999
    repeated = design._analyze_colors(source)
    assert repeated["rgb_means"] == expected
    assert repeated["rgb_metric"]["value"] == expected
    assert repeated["saturation_metric"]["available"] is True


def test_same_path_source_replacement_invalidates_color_cache(color_clip):
    source = color_clip("red")
    replacement = color_clip("blue", name="replacement.mkv")
    design = DesignQualityGuardrails()
    before = design._analyze_colors(source)
    original_stat = Path(source).stat()
    os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    os.replace(replacement, source)
    after = design._analyze_colors(source)
    assert before["rgb_means"][0] > before["rgb_means"][2]
    assert after["rgb_means"][2] > after["rgb_means"][0]


def test_unavailable_rgb_is_explicit_and_failed_design_results_retry(color_clip, monkeypatch):
    source = color_clip()
    design = DesignQualityGuardrails()
    engine = _quality_engine(design)
    original = engine._get_rgb_means
    rgb = Mock(side_effect=[{"_error": {"stage": "ffprobe_rgb_means"}}, original(source)])
    monkeypatch.setattr(engine, "_get_rgb_means", rgb)
    failed = design._analyze_colors(source)
    assert failed["rgb_means"] is None
    assert failed["rgb_metric"]["available"] is False
    assert not design._color_analysis_cache
    assert not design._is_dark_brand_theme(40, {"rgb_means": None, "saturation": None})
    recovered = design._analyze_colors(source)
    assert recovered["rgb_metric"]["available"] is True
    assert rgb.call_count == 2


def test_missing_color_is_advisory_and_does_not_fabricate_a_cast(monkeypatch):
    design = DesignQualityGuardrails()
    monkeypatch.setattr(design, "_analyze_colors", lambda source: {"rgb_means": None, "saturation": None})
    monkeypatch.setattr(design, "_get_mean_luma", lambda source: None)
    design._check_color("missing.mp4")
    assert any("Color balance analysis unavailable" in issue.message for issue in design.issues)
    assert not any("color cast detected" in issue.message for issue in design.issues)


def test_color_and_luma_measure_the_whole_clip_not_the_final_frame(color_clip, tmp_path):
    red = color_clip("red", name="red.mkv")
    blue = color_clip("blue", name="blue.mkv")
    combined = tmp_path / "combined.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            red,
            "-i",
            blue,
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "ffv1",
            str(combined),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    design = DesignQualityGuardrails()
    result = design._analyze_colors(str(combined))
    assert result["rgb_means"][0] > 50
    assert result["rgb_means"][2] > 50
    mean = design._get_mean_luma(str(combined))
    reference = VisualQualityGuardrails()
    red_luma = reference._mean_signalstat(red, "YAVG")
    blue_luma = reference._mean_signalstat(blue, "YAVG")
    assert mean == pytest.approx((red_luma + blue_luma) / 2, abs=0.01)


def test_failed_saturation_is_not_cached_as_success(color_clip, monkeypatch):
    from kinocut.quality_guardrail_types import QualityReport

    source = color_clip()
    design = DesignQualityGuardrails()
    engine = _quality_engine(design)
    successful = engine.check_saturation(source)
    failure = QualityReport("saturation", False, 0, "unavailable", {"metric": {"available": False, "value": None}})
    probe = Mock(side_effect=[failure, successful])
    monkeypatch.setattr(engine, "check_saturation", probe)
    assert design._analyze_colors(source)["saturation"] is None
    assert not design._color_analysis_cache
    assert design._analyze_colors(source)["saturation"] is not None
    assert probe.call_count == 2
