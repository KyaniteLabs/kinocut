"""Deterministic bounded word comparison, independent of the recognizer."""

import math
import time
import unicodedata

from kinocut_sound.limits import MAX_ASR_WORDS, MAX_ASR_TEXT_BYTES, MAX_ASR_SEGMENTS
from kinocut_sound.public.asr_request import asr_error


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise asr_error("ASR exceeded total deadline", "asr_timeout")
    return value


def words(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_ASR_TEXT_BYTES:
        raise asr_error("ASR text exceeds bound", "asr_over_limit")
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = "".join(c if c.isalnum() else " " for c in normalized)
    result = normalized.split()
    if len(result) > MAX_ASR_WORDS or len(" ".join(result).encode()) > MAX_ASR_TEXT_BYTES:
        raise asr_error("ASR normalized text exceeds bound", "asr_over_limit")
    return result


def compare(reference, hypothesis, deadline):
    expected, observed = words(reference), words(hypothesis)
    if not expected:
        raise asr_error("ASR reference must contain words")
    # Each cell retains distance, substitutions, deletions, insertions.
    previous = [(j, 0, 0, j) for j in range(len(observed) + 1)]
    for i, token in enumerate(expected, 1):
        remaining(deadline)
        current = [(i, 0, i, 0)]
        for j, actual in enumerate(observed, 1):
            if token == actual:
                current.append(previous[j - 1])
                continue
            d, s, deleted, inserted = previous[j - 1]
            substitution = (d + 1, s + 1, deleted, inserted)
            d, s, deleted, inserted = previous[j]
            deletion = (d + 1, s, deleted + 1, inserted)
            d, s, deleted, inserted = current[j - 1]
            insertion = (d + 1, s, deleted, inserted + 1)
            current.append(min((substitution, deletion, insertion), key=lambda item: item[0]))
        previous = current
    distance, substitutions, deletions, insertions = previous[-1]
    return {
        "ok": distance == 0,
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "reference_words": len(expected),
        "recognized_words": len(observed),
        "word_error_rate": distance / len(expected),
        "normalization": "nfkc-casefold-alnum-v1",
        "unicode_version": unicodedata.unidata_version,
    }


def validate_segments(payload, duration, rate):
    if not isinstance(payload, dict) or set(payload) != {"text", "segments"}:
        raise asr_error("invalid ASR result schema", "asr_invalid_output")
    segments = payload["segments"]
    if not isinstance(segments, list) or len(segments) > MAX_ASR_SEGMENTS:
        raise asr_error("invalid ASR segment count", "asr_invalid_output")
    end, texts, accepted = 0.0, [], []
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != {"start", "end", "text"}:
            raise asr_error("invalid ASR segment schema", "asr_invalid_output")
        start, stop = segment["start"], segment["end"]
        if any(
            type(v) not in (int, float) or not 0 <= v <= duration + 1 / rate or not math.isfinite(v)
            for v in (start, stop)
        ):
            raise asr_error("invalid ASR segment timestamp", "asr_invalid_output")
        if not end <= start <= stop <= duration + 1 / rate:
            raise asr_error("ASR segments overlap or exceed audio", "asr_invalid_output")
        words(segment["text"])
        texts.append(segment["text"].strip())
        end = min(stop, duration)
        accepted.append({"start": min(start, duration), "end": end, "text": segment["text"]})
    transcript = " ".join(texts)
    if words(payload["text"]) != words(transcript):
        raise asr_error("ASR transcript contradicts segments", "asr_invalid_output")
    return transcript, accepted
