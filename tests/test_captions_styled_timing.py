"""Auditable Whisper-ground-truth timing through the styled ASS burn path."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from kinocut.engine_subtitles import subtitles
from kinocut.errors import MCPVideoError
from kinocut.product.captions import (
    CaptionAppearance,
    CaptionConfig,
    WordTiming,
    build_word_timed_ass_artifact,
)

_FPS = 50
_WIDTH = 320
_HEIGHT = 180
_MAX_ERROR_SECONDS = 0.08


def _run(command: list[str]) -> bytes:
    return subprocess.run(command, check=True, capture_output=True, timeout=30).stdout


def _make_black_video(path: Path) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={_WIDTH}x{_HEIGHT}:r={_FPS}:d=2.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _visible_intervals(path: Path) -> tuple[tuple[float, float], ...]:
    raw = _run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"fps={_FPS},format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    frame_size = _WIDTH * _HEIGHT
    visible = [
        sum(value > 40 for value in raw[offset : offset + frame_size]) > 10 for offset in range(0, len(raw), frame_size)
    ]
    intervals: list[tuple[float, float]] = []
    start: int | None = None
    for index, is_visible in enumerate((*visible, False)):
        if is_visible and start is None:
            start = index
        elif not is_visible and start is not None:
            intervals.append((start / _FPS, index / _FPS))
            start = None
    return tuple(intervals)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_every_styled_burned_word_is_within_80ms_of_whisper_ground_truth(tmp_path: Path) -> None:
    ground_truth = (
        WordTiming(word="HELLO", start=0.40, end=0.90, probability=0.99),
        WordTiming(word="WORLD", start=1.20, end=1.80, probability=0.98),
    )
    artifact = build_word_timed_ass_artifact(
        ground_truth,
        appearance=CaptionAppearance(
            font_family="Arial",
            font_size=48,
            text_color="#FFFFFF",
            background_color="#000000",
        ),
        config=CaptionConfig(on_low_confidence="flag"),
        play_res_x=_WIDTH,
        play_res_y=_HEIGHT,
    )
    source = tmp_path / "source.mp4"
    captions = tmp_path / "captions.ass"
    output = tmp_path / "burned.mp4"
    _make_black_video(source)
    captions.write_text(artifact.ass_body, encoding="utf-8")

    subtitles(str(source), str(captions), output_path=str(output))

    measured = _visible_intervals(output)
    expected = tuple((word.start, word.end) for word in ground_truth)
    assert len(measured) == len(expected)
    assert (
        max(
            abs(actual - truth)
            for pair, expected_pair in zip(measured, expected, strict=True)
            for actual, truth in zip(pair, expected_pair, strict=True)
        )
        <= _MAX_ERROR_SECONDS
    )
    assert artifact.maximum_quantization_error_seconds <= 0.005


def test_styled_caption_export_preserves_low_confidence_policy_and_zero_drift() -> None:
    words = tuple(
        WordTiming(
            word=f"word-{index}",
            start=index * 0.6,
            end=index * 0.6 + 0.4,
            probability=0.1 if index == 50 else 0.99,
        )
        for index in range(100)
    )
    artifact = build_word_timed_ass_artifact(
        words,
        appearance=CaptionAppearance(
            font_family="Arial",
            font_size=42,
            text_color="#FFFFFF",
            background_color="#000000",
        ),
        config=CaptionConfig(on_low_confidence="omit"),
        play_res_x=1080,
        play_res_y=1920,
    )

    assert artifact.caption.omitted_token_count == 1
    assert "word-50" not in artifact.ass_body
    assert "0:00:59.80" in artifact.ass_body
    assert artifact.maximum_quantization_error_seconds <= 0.005


def test_styled_caption_export_rejects_ass_style_injection() -> None:
    with pytest.raises(MCPVideoError):
        build_word_timed_ass_artifact(
            (WordTiming(word="safe", start=0.0, end=0.5, probability=0.99),),
            appearance=CaptionAppearance(
                font_family="Arial,Injected",
                font_size=42,
                text_color="#FFFFFF",
                background_color="#000000",
            ),
            play_res_x=1080,
            play_res_y=1920,
        )
