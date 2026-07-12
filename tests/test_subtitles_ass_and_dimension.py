"""Authored-ASS preservation and dimension-aware SRT/VTT rendering tests."""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.subtitles_eof import ClampedSegment
from tests.subtitle_render_test_support import (
    _ASPECTS,
    _AUTHORED_ASS,
    _extract_ppm,
    _ffprobe_json,
    _has_audio,
    _make_solid_video,
    _make_testsrc_video,
    _region_peak_diff,
    _subtitles_common,
    _video_stream,
    requires_ffmpeg,
)


@pytest.fixture(params=list(_ASPECTS), ids=list(_ASPECTS))
def aspect_video(request, tmp_path):
    width, height = _ASPECTS[request.param]
    return _make_testsrc_video(tmp_path / f"{request.param}.mp4", width, height), (width, height)


@pytest.fixture(params=list(_ASPECTS), ids=list(_ASPECTS))
def solid_aspect_video(request, tmp_path):
    width, height = _ASPECTS[request.param]
    return _make_solid_video(tmp_path / f"solid_{request.param}.mp4", width, height), (width, height)


@pytest.fixture
def srt_file(tmp_path):
    path = tmp_path / "cues.srt"
    path.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHELLO WORLD\n",
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def vtt_file(tmp_path):
    path = tmp_path / "cues.vtt"
    path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHELLO WORLD\n",
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def authored_ass_file(tmp_path):
    path = tmp_path / "authored.ass"
    path.write_text(_AUTHORED_ASS, encoding="utf-8")
    return str(path)


# --- closed format detection (ass/srt/vtt only) ---------------------------- #


@pytest.mark.parametrize(
    "name,fmt",
    [("x.srt", "srt"), ("x.vtt", "vtt"), ("x.ass", "ass"), ("X.SRT", "srt"), ("clip.VTT", "vtt")],
)
def test_render_subtitle_format_detection(name, fmt):
    assert _subtitles_common()._subtitle_format(name) == fmt


@pytest.mark.parametrize("bad", ["x.ssa", "x.txt", "x.mp4", "noext", "x.srt.exe"])
def test_render_unsupported_subtitle_format_is_rejected(bad):
    with pytest.raises(MCPVideoError) as excinfo:
        _subtitles_common()._subtitle_format(bad)
    assert excinfo.value.code == "unsupported_subtitle_format"


# --- style secured by a closed key parser (reject hostile, no echo) -------- #


def test_render_valid_style_is_parsed():
    parsed = _subtitles_common().parse_force_style("FontSize=22,PrimaryColour=&Hffffff&")
    assert "FontSize=22" in parsed
    assert "PrimaryColour=&Hffffff&" in parsed


@pytest.mark.parametrize(
    "hostile",
    [
        "FontSize=22'",  # single quote (quote breakout)
        "FontSize=22\\",  # backslash
        "FontSize=2;drawtext",  # filtergraph separator
        "FontSize=2\n",  # newline / control
        "FontSize=2\x00",  # NUL control char
        "Nonexistent=1",  # key outside the closed set
    ],
)
def test_render_hostile_style_is_rejected_without_echo(hostile):
    with pytest.raises(MCPVideoError) as excinfo:
        _subtitles_common().parse_force_style(hostile)
    assert excinfo.value.code == "invalid_subtitle_style"
    assert hostile not in str(excinfo.value)  # never echo the raw hostile value


@pytest.mark.parametrize("bad", [123, ["FontSize=22"], {"FontSize": 22}, b"FontSize=22"])
def test_render_non_string_style_is_rejected_without_echo(bad):
    with pytest.raises(MCPVideoError) as excinfo:
        _subtitles_common().parse_force_style(bad)
    assert excinfo.value.code == "invalid_subtitle_style"
    assert repr(bad) not in str(excinfo.value)  # no raw value echo


# --- entry validation widened to Mapping (ClampedSegment consumers) -------- #


def test_render_validate_entries_accepts_mapping_records():
    from kinocut.engine_subtitle_generate import _validate_entries

    seg = ClampedSegment(0.0, 2.0, {"text": "hi"})
    _validate_entries([seg])  # a Mapping record must be accepted, not just dict


def test_render_build_srt_content_reads_mapping_entries():
    from kinocut.engine_subtitle_generate import _build_srt_content

    seg = ClampedSegment(0.0, 1.0, {"text": "hi"})
    out = _build_srt_content([seg])
    assert "hi" in out
    assert "00:00:00,000 --> 00:00:01,000" in out


# --- real-FFmpeg: probe + dimensioned-ASS synthesis + EOF clamp ------------ #


@requires_ffmpeg
def test_render_probe_display_dimensions(aspect_video):
    path, (width, height) = aspect_video
    assert _subtitles_common().probe_display_dimensions(path) == (width, height)


@requires_ffmpeg
@pytest.mark.parametrize("fmt", ["srt", "vtt"])
def test_render_synthesized_ass_has_exactly_one_playres_equal_dims(fmt, srt_file, vtt_file):
    sub = srt_file if fmt == "srt" else vtt_file
    ass = _subtitles_common().synthesize_dimensioned_ass(sub, (1080, 1920))
    xs = re.findall(r"(?mi)^\s*PlayResX:\s*(\d+)", ass)
    ys = re.findall(r"(?mi)^\s*PlayResY:\s*(\d+)", ass)
    assert xs == ["1080"]  # exactly one PlayResX, equal to display width
    assert ys == ["1920"]  # exactly one PlayResY, equal to display height


@requires_ffmpeg
def test_render_generate_subtitles_clamps_entries_to_video_eof(tmp_path):
    from kinocut.engine_subtitle_generate import generate_subtitles

    video = _make_testsrc_video(tmp_path / "v.mp4", 256, 256, seconds=3)
    # Chronological cues (the clamp requires ordered, non-overlapping input): the
    # last two straddle the ~3s EOF — one overshoots and one starts past it.
    entries = [
        {"start": 0.0, "end": 2.0, "text": "early"},
        {"start": 2.0, "end": 4.0, "text": "overshoot"},  # end past EOF -> clamped
        {"start": 4.0, "end": 6.0, "text": "afterward"},  # starts past EOF -> dropped
    ]
    result = generate_subtitles(entries, video, output_path=str(tmp_path / "out.srt"))
    content = Path(result.srt_path).read_text(encoding="utf-8")
    assert "overshoot" in content
    assert "afterward" not in content  # wholly-past-EOF cue dropped
    assert "00:00:04" not in content  # neither the 4s overshoot end nor the dropped cue survive


@requires_ffmpeg
def test_render_generate_propagates_clamp_warnings(tmp_path):
    from kinocut.engine_subtitle_generate import generate_subtitles

    video = _make_testsrc_video(tmp_path / "v.mp4", 256, 256, seconds=3)
    entries = [
        {"start": 0.0, "end": 2.0, "text": "early"},
        {"start": 2.0, "end": 9.0, "text": "over"},  # end past EOF -> clamped
        {"start": 9.0, "end": 12.0, "text": "after"},  # starts past EOF -> dropped
    ]
    result = generate_subtitles(entries, video, output_path=str(tmp_path / "out.srt"))
    assert "segment_clamped_to_eof" in result.warnings
    assert "segment_dropped_after_eof" in result.warnings


@requires_ffmpeg
def test_render_generate_burn_does_not_clobber_sibling_srt(solid_aspect_video, tmp_path):
    from kinocut.engine_subtitle_generate import generate_subtitles

    path, _dims = solid_aspect_video
    out = tmp_path / "burned"  # extensionless -> SRT is written to "burned"
    sibling = tmp_path / "burned.srt"  # a pre-existing user file that must survive
    sibling.write_text("PRECIOUS-DO-NOT-OVERWRITE", encoding="utf-8")
    generate_subtitles([{"start": 0.0, "end": 1.0, "text": "hi"}], path, output_path=str(out), burn=True)
    assert sibling.read_text(encoding="utf-8") == "PRECIOUS-DO-NOT-OVERWRITE"


@requires_ffmpeg
def test_render_generate_burn_handles_misleading_output_suffix(solid_aspect_video, tmp_path):
    from kinocut.engine_subtitle_generate import generate_subtitles

    # generate_subtitles always writes SRT content; a .vtt-named output must be
    # burned as SRT (via a temp .srt), not misread as WebVTT by the suffix.
    path, _dims = solid_aspect_video
    out = tmp_path / "cues.vtt"
    result = generate_subtitles([{"start": 0.0, "end": 1.0, "text": "hi"}], path, output_path=str(out), burn=True)
    assert Path(result.video_path).is_file()


# --- authored-ASS preservation: source bytes + pixel position -------------- #


@requires_ffmpeg
def test_render_authored_ass_source_bytes_unchanged(solid_aspect_video, authored_ass_file, tmp_path):
    from kinocut.engine_subtitles import subtitles

    before = hashlib.sha256(Path(authored_ass_file).read_bytes()).hexdigest()
    path, _dims = solid_aspect_video
    subtitles(path, authored_ass_file, output_path=str(tmp_path / "o.mp4"))
    after = hashlib.sha256(Path(authored_ass_file).read_bytes()).hexdigest()
    assert before == after  # authored ASS is never rewritten


@requires_ffmpeg
def test_render_authored_ass_position_is_centered(solid_aspect_video, authored_ass_file, tmp_path):
    from kinocut.engine_subtitles import subtitles

    path, _dims = solid_aspect_video
    out = str(tmp_path / "o.mp4")
    subtitles(path, authored_ass_file, output_path=out)
    src = _extract_ppm(path, 1.0)
    dst = _extract_ppm(out, 1.0)
    center = _region_peak_diff(src, dst, (0.30, 0.35, 0.70, 0.65))
    top = _region_peak_diff(src, dst, (0.0, 0.0, 1.0, 0.12))
    assert center > 80  # authored \pos renders bright text at the center
    assert top < 40  # header stays black -> not bottom/edge-defaulted; PlayRes/pos preserved


# --- dimension-aware caption pixels: VTT + SRT across all 3 aspects --------- #


@requires_ffmpeg
@pytest.mark.parametrize("fmt", ["srt", "vtt"])
def test_render_dimension_aware_caption_renders_in_frame(fmt, solid_aspect_video, srt_file, vtt_file, tmp_path):
    from kinocut.engine_subtitles import subtitles

    sub = srt_file if fmt == "srt" else vtt_file
    path, _dims = solid_aspect_video
    out = str(tmp_path / f"o_{fmt}.mp4")
    subtitles(path, sub, output_path=out)
    src = _extract_ppm(path, 1.0)
    dst = _extract_ppm(out, 1.0)
    bottom = _region_peak_diff(src, dst, (0.10, 0.62, 0.90, 0.99))
    top = _region_peak_diff(src, dst, (0.0, 0.0, 1.0, 0.12))
    assert bottom > 80  # caption is rendered in-frame at the bottom for this aspect
    assert top < 40  # header region untouched


# --- audio / duration / resolution preservation ---------------------------- #


@requires_ffmpeg
def test_render_burn_preserves_audio_duration_resolution(solid_aspect_video, srt_file, tmp_path):
    from kinocut.engine_subtitles import subtitles

    path, (width, height) = solid_aspect_video
    out = str(tmp_path / "o.mp4")
    subtitles(path, srt_file, output_path=out)
    src, dst = _ffprobe_json(path), _ffprobe_json(out)
    vstream = _video_stream(dst)
    assert (int(vstream["width"]), int(vstream["height"])) == (width, height)
    assert _has_audio(dst)  # audio track preserved
    assert abs(float(dst["format"]["duration"]) - float(src["format"]["duration"])) < 0.4


# --- generate(burn=True) delegates to the canonical dimension-aware engine -- #


@requires_ffmpeg
def test_render_generate_burn_delegates_to_canonical_engine(solid_aspect_video, tmp_path):
    from kinocut.engine_subtitle_generate import generate_subtitles

    path, (width, height) = solid_aspect_video
    entries = [
        {"start": 0.0, "end": 1.0, "text": "early"},
        {"start": 1.0, "end": 9.0, "text": "late"},  # past ~2s EOF -> clamped before write
    ]
    result = generate_subtitles(entries, path, output_path=str(tmp_path / "g.srt"), burn=True)
    assert Path(result.video_path).is_file()
    assert "segment_clamped_to_eof" in result.warnings  # clamp warnings survive the burn path
    vstream = _video_stream(_ffprobe_json(result.video_path))
    assert (int(vstream["width"]), int(vstream["height"])) == (width, height)


# --- hostile subtitle filename + temp cleanup (success and failure) --------- #


@requires_ffmpeg
def test_render_hostile_subtitle_filename_is_escaped(solid_aspect_video, tmp_path):
    from kinocut.engine_subtitles import subtitles

    path, _dims = solid_aspect_video
    tricky = tmp_path / "a'b;c,d.srt"
    tricky.write_text("1\n00:00:00,000 --> 00:00:02,000\nHI\n", encoding="utf-8")
    out = str(tmp_path / "o.mp4")
    subtitles(path, str(tricky), output_path=out)  # metacharacters must not break the filtergraph
    assert Path(out).is_file()


@requires_ffmpeg
def test_render_srt_burn_uses_synthesized_ass(monkeypatch, aspect_video, srt_file, tmp_path):
    import kinocut.engine_subtitles as engine_subtitles

    captured: dict = {}

    class _Stop(Exception):
        pass

    def _capture(args):
        captured["args"] = list(args)
        raise _Stop()

    monkeypatch.setattr(engine_subtitles, "_run_ffmpeg", _capture)
    path, _dims = aspect_video
    with pytest.raises(_Stop):
        engine_subtitles.subtitles(path, srt_file, output_path=str(tmp_path / "o.mp4"))
    cmd = " ".join(captured["args"])
    assert "subtitles=" in cmd
    assert ".ass" in cmd  # SRT is burned through a synthesized (dimensioned) ASS


@requires_ffmpeg
def test_render_temp_ass_cleanup_observes_injected_root_on_success(monkeypatch, aspect_video, srt_file, tmp_path):
    import kinocut.engine_subtitles as engine_subtitles

    workdir = tmp_path / "synthwork"
    workdir.mkdir()
    monkeypatch.setattr(engine_subtitles, "_synthesis_workdir", lambda output_path: str(workdir))
    path, _dims = aspect_video
    engine_subtitles.subtitles(path, srt_file, output_path=str(tmp_path / "o.mp4"))
    assert list(workdir.glob("*.ass")) == []  # transient cleaned in the real (injected) temp root


@requires_ffmpeg
def test_render_temp_ass_cleanup_observes_injected_root_on_failure(monkeypatch, aspect_video, srt_file, tmp_path):
    import kinocut.engine_subtitles as engine_subtitles

    workdir = tmp_path / "synthwork"
    workdir.mkdir()
    monkeypatch.setattr(engine_subtitles, "_synthesis_workdir", lambda output_path: str(workdir))
    seen: dict = {}

    def _boom(args):
        # At burn time the transient ASS must already exist in the injected root.
        seen["ass_present"] = bool(list(workdir.glob("*.ass")))
        raise MCPVideoError("burn failed", error_type="processing_error", code="ffmpeg_error")

    monkeypatch.setattr(engine_subtitles, "_run_ffmpeg", _boom)
    path, _dims = aspect_video
    with pytest.raises(MCPVideoError):
        engine_subtitles.subtitles(path, srt_file, output_path=str(tmp_path / "o.mp4"))
    assert seen.get("ass_present") is True  # temp was actually created in the injected root
    assert list(workdir.glob("*.ass")) == []  # ...and cleaned despite the failure


# --- authored ASS burn omits default force_style (captured command) -------- #


@requires_ffmpeg
def test_render_authored_ass_burn_omits_default_force_style(monkeypatch, authored_ass_file, tmp_path):
    import kinocut.engine_subtitles as engine_subtitles

    captured: dict = {}

    class _Stop(Exception):
        pass

    def _capture(args):
        captured["args"] = list(args)
        raise _Stop()

    monkeypatch.setattr(engine_subtitles, "_run_ffmpeg", _capture)
    monkeypatch.setattr(engine_subtitles, "_validate_input_path", lambda p: p)
    with pytest.raises(_Stop):
        engine_subtitles.subtitles("in.mp4", authored_ass_file, output_path=str(tmp_path / "o.mp4"))
    cmd = " ".join(captured["args"])
    assert "subtitles=" in cmd
    assert "force_style" not in cmd  # a default authored-ASS burn is never clobbered


@requires_ffmpeg
def test_render_authored_ass_burn_applies_explicit_style(monkeypatch, authored_ass_file, tmp_path):
    import kinocut.engine_subtitles as engine_subtitles

    captured: dict = {}

    class _Stop(Exception):
        pass

    def _capture(args):
        captured["args"] = list(args)
        raise _Stop()

    monkeypatch.setattr(engine_subtitles, "_run_ffmpeg", _capture)
    monkeypatch.setattr(engine_subtitles, "_validate_input_path", lambda p: p)
    with pytest.raises(_Stop):
        engine_subtitles.subtitles(
            "in.mp4", authored_ass_file, output_path=str(tmp_path / "o.mp4"), style="FontSize=40"
        )
    cmd = " ".join(captured["args"])
    assert "force_style" in cmd and "FontSize=40" in cmd  # explicit ASS style is an intentional override


# --- behavioral style forwarding across MCP / Client / CLI ----------------- #


def test_render_mcp_forwards_style_and_defaults_none(monkeypatch):
    import kinocut.server_tools_media as stm

    captured: dict = {}

    def _capture(input_path, **kwargs):
        captured.clear()
        captured["input"] = input_path
        captured.update(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(stm, "_validate_input_path", lambda p: p)
    monkeypatch.setattr(stm, "subtitles", _capture)

    stm.video_subtitles("in.mp4", "c.srt", output_path="o.mp4", style="FontSize=22")
    assert captured.get("input") == "in.mp4"
    assert captured.get("style") == "FontSize=22"

    stm.video_subtitles("in.mp4", "c.srt", output_path="o.mp4")
    assert captured.get("input") == "in.mp4"  # engine reached
    assert captured.get("style") is None  # omission defaults to None


def test_render_client_forwards_style_and_defaults_none(monkeypatch):
    import kinocut.client.media as client_media

    captured: dict = {}

    def _capture(video, **kwargs):
        captured.clear()
        captured["video"] = video
        captured.update(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(client_media, "_subtitles", _capture)
    from kinocut import Client

    client = Client()
    with contextlib.suppress(Exception):
        client.subtitles(video="in.mp4", subtitle_file="c.srt", output="o.mp4", style="FontSize=22")
    assert captured.get("video") == "in.mp4"
    assert captured.get("style") == "FontSize=22"

    with contextlib.suppress(Exception):
        client.subtitles(video="in.mp4", subtitle_file="c.srt", output="o.mp4")
    assert captured.get("video") == "in.mp4"  # engine reached
    assert captured.get("style") is None  # omission defaults to None


def test_render_cli_forwards_style_and_defaults_none(monkeypatch):
    import argparse

    import kinocut.engine as engine
    from kinocut.cli.handlers_core import handle_initial_command

    captured: dict = {}

    def _capture(input_path, **kwargs):
        captured.clear()
        captured["input"] = input_path
        captured.update(kwargs)
        raise RuntimeError("stop")

    monkeypatch.setattr(engine, "subtitles", _capture)

    def _ns(style):
        return argparse.Namespace(
            command="subtitles", input="in.mp4", subtitle="c.srt", output="o.mp4", style=style, json=True
        )

    with pytest.raises(RuntimeError):
        handle_initial_command(_ns("FontSize=22"), use_json=True)
    assert captured.get("style") == "FontSize=22"

    with pytest.raises(RuntimeError):
        handle_initial_command(_ns(None), use_json=True)
    assert captured.get("input") == "in.mp4"  # engine reached
    assert "style" not in captured  # omitted -> not forwarded (engine default None)


def test_render_cli_subtitles_parser_has_style_flag():
    import argparse

    from kinocut.cli.parser.media import add_parsers

    parser = argparse.ArgumentParser()
    add_parsers(parser.add_subparsers())
    namespace = parser.parse_args(["subtitles", "in.mp4", "c.srt", "--style", "FontSize=22"])
    assert namespace.style == "FontSize=22"


# --- docs / skill document subtitle style + formats ------------------------ #


@pytest.mark.parametrize("doc", ["docs/TOOLS.md", "docs/CLI_REFERENCE.md", "skills/kinocut/SKILL.md"])
def test_render_docs_document_subtitle_style_and_formats(doc):
    text = Path(doc).read_text(encoding="utf-8").lower()
    assert "subtitle" in text
    assert "style" in text
    assert "srt" in text and "vtt" in text
    assert ".ass" in text or "ass subtitle" in text


# --- generate entry type validation: private, no echo, no partial output --- #


@pytest.mark.parametrize(
    "entry",
    [
        {"start": "/" + "opt/hostile-time", "end": 5.0, "text": "x"},  # path-like time value
        {"start": 0.0, "end": "5", "text": "x"},  # mixed time type (str)
        {"start": True, "end": 5.0, "text": "x"},  # bool masquerading as time
        {"start": 0.0, "end": 5.0, "text": 123},  # non-string text
        {"start": 0.0, "end": 5.0, "text": ["nope"]},  # non-string text
    ],
)
def test_render_generate_rejects_bad_entry_types_privately(entry, tmp_path):
    from kinocut.engine_subtitle_generate import generate_subtitles

    with pytest.raises(MCPVideoError) as excinfo:
        generate_subtitles([entry], "nonexistent-input.mp4", output_path=str(tmp_path / "o.srt"))
    assert excinfo.value.code == "invalid_parameter"
    assert ("/" + "opt/hostile-time") not in str(excinfo.value)  # no raw value echo
    assert list(tmp_path.glob("*.srt")) == []  # no partial output written


# --- explicit empty style is invalid across engine / MCP / Python ---------- #


@requires_ffmpeg
def test_render_explicit_empty_style_rejected_engine(solid_aspect_video, srt_file, tmp_path):
    from kinocut.engine_subtitles import subtitles

    path, _dims = solid_aspect_video
    with pytest.raises(MCPVideoError) as excinfo:
        subtitles(path, srt_file, output_path=str(tmp_path / "o.mp4"), style="")
    assert excinfo.value.code == "invalid_subtitle_style"


@requires_ffmpeg
def test_render_explicit_empty_style_rejected_client(solid_aspect_video, srt_file, tmp_path):
    from kinocut import Client

    path, _dims = solid_aspect_video
    with pytest.raises(MCPVideoError) as excinfo:
        Client().subtitles(video=path, subtitle_file=srt_file, output=str(tmp_path / "o.mp4"), style="")
    assert excinfo.value.code == "invalid_subtitle_style"


@requires_ffmpeg
def test_render_explicit_empty_style_rejected_mcp(solid_aspect_video, srt_file, tmp_path):
    import json

    from kinocut.server_tools_media import video_subtitles

    path, _dims = solid_aspect_video
    result = video_subtitles(path, srt_file, output_path=str(tmp_path / "o.mp4"), style="")
    assert "invalid_subtitle_style" in json.dumps(result)  # surfaced as a structured error


# --- CLI subtitle help documents ASS + authored-ASS hostile path escaping --- #


def test_render_cli_subtitles_help_mentions_ass():
    import argparse

    from kinocut.cli.parser.media import add_parsers

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    add_parsers(subparsers)
    help_text = subparsers.choices["subtitles"].format_help().lower()
    assert ".ass" in help_text  # literal — cannot pass on an incidental "ass" substring
    assert "style" in help_text


@requires_ffmpeg
def test_render_authored_ass_hostile_filename_is_escaped(solid_aspect_video, tmp_path):
    from kinocut.engine_subtitles import subtitles

    path, _dims = solid_aspect_video
    # Cover every filter-path escape class the reviewer named: quote, colon,
    # comma, brackets, semicolon.
    tricky = tmp_path / "a'b;c,d:e[f]g.ass"
    tricky.write_text(_AUTHORED_ASS, encoding="utf-8")
    out = str(tmp_path / "o.mp4")
    subtitles(path, str(tricky), output_path=out)  # metacharacters must not break the filtergraph
    assert Path(out).is_file()


@requires_ffmpeg
@pytest.mark.parametrize("failing", ["mkstemp", "copyfileobj"])
def test_render_authored_ass_staging_failure_is_wrapped_and_cleaned(
    failing, monkeypatch, solid_aspect_video, authored_ass_file, tmp_path
):
    import kinocut.engine_subtitles as engine_subtitles

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    # Every staging OSError (temp creation OR the byte copy) must be wrapped.
    if failing == "mkstemp":
        monkeypatch.setattr(engine_subtitles.tempfile, "mkstemp", _boom)
    else:
        monkeypatch.setattr(engine_subtitles.shutil, "copyfileobj", _boom)
    path, _dims = solid_aspect_video
    with pytest.raises(MCPVideoError) as excinfo:
        engine_subtitles.subtitles(path, authored_ass_file, output_path=str(tmp_path / "o.mp4"))
    assert excinfo.value.code == "subtitle_prepare_failed"  # OSError wrapped privately
    assert str(tmp_path) not in str(excinfo.value)  # no path echo
    assert "disk full" not in str(excinfo.value)  # raw OSError text not surfaced
    assert not (tmp_path / "o.mp4").exists()  # no partial output produced
    # No temp (tmp* prefix) leaks; the authored source survives.
    assert list(tmp_path.glob("tmp*.ass")) == []
    assert Path(authored_ass_file).is_file()


@requires_ffmpeg
def test_render_srt_synthesis_failure_closes_fd_and_cleans_temp(monkeypatch, aspect_video, srt_file, tmp_path):
    import kinocut.engine_subtitles as engine_subtitles

    created: dict = {}
    real_mkstemp = engine_subtitles.tempfile.mkstemp

    def _spy_mkstemp(*args, **kwargs):
        fd, temp = real_mkstemp(*args, **kwargs)
        created["fd"] = fd
        return fd, temp

    def _boom_probe(_path):
        raise MCPVideoError("no video stream", error_type="validation_error", code="no_video_stream")

    monkeypatch.setattr(engine_subtitles.tempfile, "mkstemp", _spy_mkstemp)
    monkeypatch.setattr(engine_subtitles, "probe_display_dimensions", _boom_probe)
    path, _dims = aspect_video
    with pytest.raises(MCPVideoError) as excinfo:
        engine_subtitles.subtitles(path, srt_file, output_path=str(tmp_path / "o.mp4"))
    assert excinfo.value.code == "no_video_stream"  # custom probe error preserved (not re-wrapped)
    with pytest.raises(OSError):
        os.close(created["fd"])  # fd was closed by _fill_burn_source
    assert list(tmp_path.glob("tmp*.ass")) == []  # temp removed despite the failure
    assert not (tmp_path / "o.mp4").exists()


@requires_ffmpeg
def test_render_srt_write_failure_is_private_without_raw_message(monkeypatch, aspect_video, srt_file, tmp_path):
    import kinocut.engine_subtitles as engine_subtitles

    def _boom_fdopen(*args, **kwargs):
        raise OSError("disk full secret detail")

    monkeypatch.setattr(engine_subtitles.os, "fdopen", _boom_fdopen)
    path, _dims = aspect_video
    with pytest.raises(MCPVideoError) as excinfo:
        engine_subtitles.subtitles(path, srt_file, output_path=str(tmp_path / "o.mp4"))
    assert excinfo.value.code == "subtitle_prepare_failed"  # non-ASS write OSError wrapped
    assert "disk full secret detail" not in str(excinfo.value)  # raw OS message not surfaced
    assert not (tmp_path / "o.mp4").exists()  # no partial output
    assert list(tmp_path.glob("tmp*.ass")) == []  # no temp leak
