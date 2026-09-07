"""Recognition comparisons cannot turn missing or different words into a pass."""

import time

import pytest

from kinocut_sound.public.asr_compare import compare, validate_segments, words
from kinocut_sound.public.asr_request import AsrError, real_mode


@pytest.mark.parametrize(
    "reference,actual,counts",
    [
        ("Hello, WORLD!", "hello world", (0, 0, 0)),
        ("one two", "one three", (1, 0, 0)),
        ("one two", "one", (0, 1, 0)),
        ("one", "one two three", (0, 0, 2)),
        ("one two", "", (0, 2, 0)),
        ("CAFÉ", "cafe\u0301", (0, 0, 0)),
    ],
)
def test_word_comparison(reference, actual, counts):
    result = compare(reference, actual, time.monotonic() + 10)
    assert tuple(result[key] for key in ("substitutions", "deletions", "insertions")) == counts
    assert result["ok"] is (sum(counts) == 0)
    assert result["word_error_rate"] == sum(counts) / result["reference_words"]


@pytest.mark.parametrize("text", ["x " * 2049, "x" * 32769])
def test_text_limits(text):
    with pytest.raises(AsrError):
        words(text)


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "wrong", "segments": [{"start": 0, "end": 1, "text": "right"}]},
        {"text": "a", "segments": [{"start": True, "end": 1, "text": "a"}]},
        {"text": "a", "segments": [{"start": 0, "end": float("nan"), "text": "a"}]},
        {"text": "a b", "segments": [{"start": 0, "end": 2, "text": "a"}, {"start": 1, "end": 3, "text": "b"}]},
        {"text": "a", "segments": [{"start": 0, "end": 4, "text": "a"}]},
    ],
)
def test_invalid_backend_segments(payload):
    with pytest.raises(AsrError):
        validate_segments(payload, 3, 16000)


@pytest.mark.parametrize(
    "arguments",
    [
        {"request": None},
        {"project_root": "."},
        {"unknown": 1},
        {"request": {}, "project_root": ".", "script_hashes": []},
        {"request": {}, "project_root": ".", "audio_duration_seconds": True},
        {"request": {}, "project_root": ".", "available": False},
    ],
)
def test_no_silent_fallback(arguments):
    with pytest.raises(AsrError):
        real_mode(arguments)


def test_default_arguments_are_compatible_and_empty_recognition_is_valid():
    assert real_mode({"request": {}, "project_root": ".", "script_hashes": None, "audio_duration_seconds": 1.0})
    assert validate_segments({"text": "", "segments": []}, 3, 16000) == ("", [])
