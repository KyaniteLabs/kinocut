"""Regression tests for the 2026-06-12 Tier 1 remediation.

Each test reproduces a verified defect, against real FFmpeg where the
defect only manifests outside mocked runs (the doctor-probe failure class).
"""

from __future__ import annotations

import shutil

import pytest

from mcp_video.ai_engine import color as color_module
from mcp_video.engine import add_audio, add_text, merge, resize, subtitles
from mcp_video.engine_probe import _build_video_info, probe
from mcp_video.engine_split_screen import _split_filter
from mcp_video.errors import MCPVideoError
from mcp_video.models import VideoInfo
from mcp_video.validation import VALID_COLOR_GRADE_STYLES


# --- BUG-1: subtitle burn-in must not escape force_style's own syntax ----------


def test_subtitles_force_style_keeps_ass_syntax(monkeypatch, sample_video, sample_srt, tmp_path):
    """force_style is `Key=Value,Key=Value` ASS syntax; escaping the `=` and `,`
    hands FFmpeg one uninterpretable token and styling is silently dropped."""
    import mcp_video.engine_subtitles as engine_subtitles

    captured: dict[str, list[str]] = {}

    def fake_run_ffmpeg(args, **kwargs):
        captured["args"] = list(args)
        shutil.copy(sample_video, args[-1])

    monkeypatch.setattr(engine_subtitles, "_run_ffmpeg", fake_run_ffmpeg)

    out = str(tmp_path / "subtitled.mp4")
    subtitles(sample_video, sample_srt, output_path=out)

    vf = next(arg for arg in captured["args"] if arg.startswith("subtitles="))
    assert "force_style='FontSize=22,PrimaryColour=" in vf
    assert "\\=" not in vf.split("force_style", 1)[1]


def test_subtitles_burn_in_succeeds_with_default_style(sample_video, sample_srt, tmp_path):
    out = str(tmp_path / "subtitled_real.mp4")
    result = subtitles(sample_video, sample_srt, output_path=out)
    assert result.success
    assert probe(out).duration > 0


# --- BUG-2: add_audio(mix=True, start_time=...) must honor the delay -----------


def test_add_audio_mix_with_start_time_applies_delay(sample_video, sample_audio, tmp_path):
    """The old graph referenced [1:a] twice in one chain — invalid filtergraph
    syntax that some FFmpeg builds tolerate. Pin the fixed graph: a delayed added
    track still mixes and produces a valid AAC stream. Under the loss-proof
    default (duration_policy='keep_video'), the output is capped at the source
    video duration — the delayed added audio that extends past the video is
    trimmed rather than stretching the output past the video."""
    out = str(tmp_path / "mixed.mp4")
    result = add_audio(sample_video, sample_audio, mix=True, start_time=1.0, output_path=out)
    assert result.success
    info = probe(out)
    assert info.audio_codec is not None
    video_duration = probe(sample_video).duration
    assert abs(info.duration - video_duration) < 0.3  # capped at the video, not stretched


# --- BUG-8 (issue #8): replace-branch start_time + volume/fade must coexist -----


def test_add_audio_replace_with_start_time_and_filters(sample_video, sample_audio, tmp_path):
    """start_time emits -filter_complex (adelay) while volume/fade emitted -af on
    the SAME output stream — FFmpeg rejects mixing simple and complex filtering.
    The delay and the volume/fade filters must share one filtergraph chain."""
    out = str(tmp_path / "delayed_faded.mp4")
    result = add_audio(
        sample_video,
        sample_audio,
        volume=0.5,
        fade_in=0.2,
        fade_out=0.3,
        start_time=0.5,
        output_path=out,
    )
    assert result.success
    info = probe(out)
    assert info.audio_codec is not None


def test_build_add_audio_args_folds_filters_into_delay_chain():
    """Unit pin: when start_time and filters coexist on the replace branch, no
    separate -af flag is emitted; filters ride inside the -filter_complex chain."""
    from mcp_video.engine_audio_ops import _build_add_audio_args

    args = _build_add_audio_args(
        "vid.mp4", "aud.wav", ["volume=0.5", "afade=t=in:st=0:d=0.2"], False, 0.5, False, "out.mp4"
    )
    assert "-af" not in args
    fc = args[args.index("-filter_complex") + 1]
    assert "adelay=500|500" in fc
    assert "volume=0.5" in fc
    assert "afade=t=in:st=0:d=0.2" in fc


# --- BUG-3: merge with transitions when audio presence differs across clips ----


def test_merge_transition_with_mixed_audio_presence(sample_video, sample_video_no_audio, tmp_path):
    """One silent clip made the audio concat reference a non-existent [i:a] pad,
    and the normalization pre-check skipped exactly this case."""
    out = str(tmp_path / "merged_mixed_audio.mp4")
    result = merge(
        [sample_video, sample_video_no_audio],
        output_path=out,
        transition="fade",
        transition_duration=0.5,
    )
    assert result.success
    assert probe(out).audio_codec is not None


# --- BUG-4: every validated color-grade style must have a real preset ----------


def test_color_grade_presets_cover_validated_styles():
    """`noir` validated OK then silently fell back to `auto`."""
    assert set(color_module.STYLE_PRESETS) >= VALID_COLOR_GRADE_STYLES


def test_color_grade_rejects_unknown_style(sample_video, tmp_path):
    with pytest.raises(MCPVideoError):
        color_module.ai_color_grade(sample_video, str(tmp_path / "graded.mp4"), style="vaporwave")


def test_color_grade_noir_runs(sample_video, tmp_path):
    out = str(tmp_path / "noir.mp4")
    assert color_module.ai_color_grade(sample_video, out, style="noir") == out
    assert probe(out).duration > 0


# --- BUG-5: single-dimension resize must produce even dimensions ---------------


def test_resize_single_width_produces_even_dimensions(sample_video, tmp_path):
    """Odd computed dimensions break yuv420p/libx264 encodes."""
    out = str(tmp_path / "resized.mp4")
    result = resize(sample_video, width=333, output_path=out)
    assert result.success
    info = probe(out)
    assert info.width % 2 == 0
    assert info.height % 2 == 0


def test_resize_single_height_produces_even_dimensions(sample_video, tmp_path):
    out = str(tmp_path / "resized_h.mp4")
    result = resize(sample_video, height=249, output_path=out)
    assert result.success
    info = probe(out)
    assert info.width % 2 == 0
    assert info.height % 2 == 0


# --- BUG-6: split_screen auto-scale must use the even-dimension idiom ----------


def test_split_filter_forces_even_auto_dimension():
    """`scale=-1` can yield odd widths; `scale=-2` is the even-safe idiom."""
    side = _split_filter(640, 480, 320, 240, "side-by-side")
    assert "scale=-1:" not in side
    assert "scale=-2:" in side

    stacked = _split_filter(640, 480, 320, 240, "stacked")
    assert ":-1," not in stacked
    assert ":-2," in stacked


# --- BUG-7: r_frame_rate "0/N" must fall back to 30 fps ------------------------


def test_probe_fps_zero_numerator_falls_back_to_30():
    """Only the zero-denominator case was guarded; "0/1" yielded fps=0.0."""
    data = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 480,
                "r_frame_rate": "0/1",
                "duration": "1.0",
            }
        ],
        "format": {"duration": "1.0", "size": "1000", "format_name": "mp4"},
    }
    info = _build_video_info("dummy.mp4", data)
    assert info.fps == 30.0


# --- BUG-8: drawtext must render user text literally (no %{...} expansion) -----


def test_add_text_disables_drawtext_expansion(monkeypatch, sample_video, tmp_path):
    """`%{...}` in user text was interpreted as a drawtext expansion token
    (FFmpeg logs "%{discount} is not known" per frame and mangles the render
    without failing). Literal user text requires expansion=none."""
    import mcp_video.engine_text as engine_text

    captured: dict[str, list[str]] = {}

    def fake_run_ffmpeg(args, **kwargs):
        captured["args"] = list(args)
        shutil.copy(sample_video, args[-1])

    monkeypatch.setattr(engine_text, "_run_ffmpeg", fake_run_ffmpeg)

    out = str(tmp_path / "percent_text.mp4")
    add_text(sample_video, "100%{discount} off", output_path=out)

    vf = next(arg for arg in captured["args"] if arg.startswith("drawtext="))
    assert "expansion=none" in vf


def test_add_text_with_percent_brace_succeeds(sample_video, tmp_path):
    out = str(tmp_path / "percent_text_real.mp4")
    result = add_text(sample_video, "100%{discount} off", output_path=out)
    assert result.success
    assert probe(out).duration > 0


# --- BUG-9: aspect_ratio must not divide by gcd(0, 0) --------------------------


def test_aspect_ratio_with_zero_dimensions_is_safe():
    info = VideoInfo(path="x.mp4", duration=0.0, width=0, height=0, fps=30.0, codec="h264")
    assert info.aspect_ratio == "unknown"


# --- SEC-2: transition whitelist must hold at the engine layer ------------------


def test_merge_rejects_unknown_transition_at_engine_layer(sample_video, sample_video_2, tmp_path):
    """The MCP tool layer validated transitions, but the Python client and CLI
    reach the engine directly with unchecked strings."""
    with pytest.raises(MCPVideoError):
        merge(
            [sample_video, sample_video_2],
            output_path=str(tmp_path / "bad_transition.mp4"),
            transition="fade;[0:v]drawtext=text=evil",
        )
