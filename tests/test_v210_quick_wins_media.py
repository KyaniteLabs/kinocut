"""Verification tests for Kinocut 2.1.0 Track A media quick wins.

Covers:
- C4-007: profile + profile_reason propagation through repurpose, shorts_package, and sphere_render.
- C3-016: shorts_flow pad-mode resizes to 9:16 BEFORE burning subtitles.
- D3-021: audition review page embeds compact AAC/M4A data URIs and falls back cleanly to WAV.
"""

from __future__ import annotations

import base64
import math
import re
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from kinocut import engine_repurpose
from kinocut.audio_sync import audition
from kinocut.errors import ProcessingError
from kinocut.product import shorts_flow, shorts_package
from kinocut.product.shorts_review import review_shorts_plan
from kinocut.te import propose_360_assembly, sphere_render
from tests.test_shorts_package import _plan_with_renders


def test_repurpose_forwards_profile_and_reason_to_assert_quality(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    seen: list[dict] = []

    monkeypatch.setattr(engine_repurpose, "_validate_input_path", lambda path: path)
    monkeypatch.setattr(
        engine_repurpose,
        "probe",
        lambda _path: SimpleNamespace(duration=5.0, display_resolution="1920x1080", aspect_ratio="16:9"),
    )
    monkeypatch.setattr(
        engine_repurpose,
        "resize",
        lambda _src, aspect_ratio, output_path: SimpleNamespace(output_path=output_path),
    )
    monkeypatch.setattr(
        engine_repurpose,
        "normalize_audio",
        lambda _src, target_lufs, output_path: SimpleNamespace(output_path=output_path),
    )
    monkeypatch.setattr(
        engine_repurpose,
        "export_video",
        lambda _src, output_path, quality, format: SimpleNamespace(output_path=output_path),
    )
    monkeypatch.setattr(
        engine_repurpose,
        "thumbnail",
        lambda _src, output_path: SimpleNamespace(output_path=output_path),
    )
    monkeypatch.setattr(
        engine_repurpose,
        "storyboard",
        lambda _src, output_dir, frame_count: SimpleNamespace(model_dump=lambda: {"frames": []}),
    )

    def capture_quality(video_path, *, min_score=80.0, profile=None, profile_reason=None):
        seen.append({"video": video_path, "min_score": min_score, "profile": profile, "profile_reason": profile_reason})
        return {"gate_passed": True, "overall_score": 92.0, "profile": {"name": profile}}

    monkeypatch.setattr(engine_repurpose, "assert_quality", capture_quality)

    result = engine_repurpose.repurpose(
        str(source),
        output_dir=str(tmp_path / "pkg"),
        platforms=["youtube"],
        profile="dark-grade",
        profile_reason="intentional moody cinema grade",
    )

    assert result["success"] is True
    assert len(seen) == 1
    assert seen[0]["profile"] == "dark-grade"
    assert seen[0]["profile_reason"] == "intentional moody cinema grade"


@pytest.mark.usefixtures("overwrite_consent")
def test_shorts_package_forwards_profile_and_reason_to_assert_quality(tmp_path, monkeypatch):
    plan = _plan_with_renders(tmp_path)
    review_shorts_plan(plan, candidate_id="candidate_01", decision="approve")
    seen: list[dict] = []

    def capture_quality(path, *, min_score=80.0, profile=None, profile_reason=None):
        seen.append({"video": path, "min_score": min_score, "profile": profile, "profile_reason": profile_reason})
        return {"video": path, "gate_passed": True, "profile": {"name": profile}}

    monkeypatch.setattr("kinocut.quality_guardrails.assert_quality", capture_quality)

    result = shorts_package.package_approved_candidate(
        plan,
        candidate_id="candidate_01",
        profile="dark-grade",
        profile_reason="dark stage lighting performance",
    )

    assert result["status"] == "packaged"
    assert len(seen) == 2
    assert all(call["profile"] == "dark-grade" for call in seen)
    assert all(call["profile_reason"] == "dark stage lighting performance" for call in seen)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg")
def test_sphere_render_forwards_profile_and_reason_to_assert_quality(tmp_path, monkeypatch):
    source = tmp_path / "sphere.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x320:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x320:d=1",
            "-filter_complex",
            "hstack=inputs=2",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
        timeout=60,
    )
    plan = propose_360_assembly(str(source), goal="desk 360 split 9:16")
    plan["status"] = "approved"
    seen: list[dict] = []

    def capture_quality(output_path, *, min_score=80.0, max_analyze_seconds=None, profile=None, profile_reason=None):
        seen.append(
            {
                "video": output_path,
                "min_score": min_score,
                "max_analyze_seconds": max_analyze_seconds,
                "profile": profile,
                "profile_reason": profile_reason,
            }
        )
        return {"video_path": output_path, "gate_passed": True, "profile": {"name": profile}}

    monkeypatch.setattr(sphere_render, "assert_quality", capture_quality)
    output = tmp_path / "sphere_out.mp4"

    receipt = sphere_render.render_sphere_plan(
        plan,
        str(output),
        work_dir=str(tmp_path / "work"),
        profile="dark-grade",
        profile_reason="nighttime 360 street scene",
    )

    assert output.is_file()
    assert receipt["quality"]["passed"] is True
    assert len(seen) == 1
    assert seen[0]["profile"] == "dark-grade"
    assert seen[0]["profile_reason"] == "nighttime 360 street scene"


def test_shorts_flow_pad_mode_resizes_before_burning_subtitles(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    order: list[tuple[str, str, str]] = []

    monkeypatch.setattr(shorts_flow, "_validate_input_path", lambda path: path)
    monkeypatch.setattr("kinocut.engine_probe.probe", lambda _path: SimpleNamespace(duration=10.0))

    def fake_trim(input_path, *, start, end, output_path, accurate=True, on_progress=None):
        Path(output_path).write_bytes(b"trimmed")
        return SimpleNamespace(output_path=output_path)

    def fake_generate(entries, input_path, output_path, burn=False):
        Path(output_path).write_text("1\n00:00:00,000 --> 00:00:02,000\nHi\n", encoding="utf-8")
        return SimpleNamespace(srt_path=output_path, entry_count=1, entries=list(entries), warnings=[])

    def fake_resize(input_path, *, aspect_ratio, output_path, quality, on_progress=None):
        order.append(("resize", str(input_path), str(output_path)))
        Path(output_path).write_bytes(b"vertical-9x16")
        return SimpleNamespace(output_path=output_path)

    def fake_burn(input_path, subtitle_path, output_path, style=None, *, qa_profile=None):
        order.append(("burn_subtitles", str(input_path), str(output_path)))
        assert qa_profile == "vertical"
        Path(output_path).write_bytes(b"vertical-captioned")
        return SimpleNamespace(output_path=output_path), {"profile": qa_profile, "passed": True, "cue_count": 1}

    monkeypatch.setattr(shorts_flow, "trim", fake_trim)
    monkeypatch.setattr(shorts_flow, "generate_subtitles", fake_generate)
    monkeypatch.setattr(shorts_flow, "resize", fake_resize)
    monkeypatch.setattr(shorts_flow, "burn_subtitles", fake_burn)

    final_output = tmp_path / "out_pad.mp4"
    result = shorts_flow.video_shorts(
        str(source),
        [{"start": 0.0, "end": 2.0, "text": "Crisp vertical caption"}],
        style={"fit_mode": "pad"},
        output_path=str(final_output),
    )

    assert result["success"] is True
    assert [step for step, _, _ in order] == ["resize", "burn_subtitles"]
    # The resized 9:16 intermediate feeds directly into burn_subtitles, which writes final_output.
    assert order[1][1] == order[0][2]
    assert order[1][2] == str(final_output)
    assert [step["stage"] for step in result["receipt"]["steps"]] == [
        "trim",
        "merge",
        "vertical_template",
        "captions",
        "export",
    ]


def _write_test_wav(path: Path, *, duration_s: float = 2.0, rate: int = 48_000, freq_hz: float = 440.0) -> Path:
    frame_count = int(duration_s * rate)
    samples = [round(0.3 * 32767 * math.sin(math.tau * freq_hz * i / rate)) for i in range(frame_count)]
    with wave.open(str(path), "wb") as handle:
        handle.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        handle.writeframes(struct.pack(f"<{frame_count}h", *samples))
    return path


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requires FFmpeg")
def test_audition_html_embeds_compact_mp4_and_falls_back_to_wav(tmp_path, monkeypatch):
    track_a = _write_test_wav(tmp_path / "mix-001.wav", duration_s=3.0, freq_hz=440.0)
    track_b = _write_test_wav(tmp_path / "mix-002.wav", duration_s=3.0, freq_hz=660.0)
    entries = [{"display_label": "Mix A"}, {"display_label": "Mix B"}]

    compact_html = tmp_path / "compact.html"
    audition._write_page(compact_html, "picture.mp4", entries, [track_a, track_b], [None, None])
    compact_text = compact_html.read_text(encoding="utf-8")

    payloads = re.findall(r'<script class="track" type="application/octet-stream">(.*?)</script>', compact_text)
    assert len(payloads) == 2
    assert all(p.startswith("data:audio/mp4;base64,") for p in payloads)
    for payload in payloads:
        raw = base64.b64decode(payload.removeprefix("data:audio/mp4;base64,"))
        assert raw[4:8] == b"ftyp"

    # Simulate FFmpeg unavailable / failing -> clean fallback to WAV data URIs.
    def fail_ffmpeg(_args):
        raise ProcessingError("ffmpeg", 1, "simulated encoder failure")

    monkeypatch.setattr(audition, "_run_ffmpeg", fail_ffmpeg)
    fallback_html = tmp_path / "fallback.html"
    audition._write_page(fallback_html, "picture.mp4", entries, [track_a, track_b], [None, None])
    fallback_text = fallback_html.read_text(encoding="utf-8")

    fallback_payloads = re.findall(
        r'<script class="track" type="application/octet-stream">(.*?)</script>', fallback_text
    )
    assert len(fallback_payloads) == 2
    assert all(p.startswith("data:audio/wav;base64,") for p in fallback_payloads)
    assert [base64.b64decode(p.removeprefix("data:audio/wav;base64,")) for p in fallback_payloads] == [
        track_a.read_bytes(),
        track_b.read_bytes(),
    ]
    # Compact AAC/M4A HTML should be dramatically smaller than inline WAV HTML (>5x smaller on 3s mono).
    assert compact_html.stat().st_size * 5 < fallback_html.stat().st_size
