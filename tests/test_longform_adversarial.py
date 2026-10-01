"""No-model controls for replay resources, event identity and truthful source timing."""

from copy import deepcopy

import pytest

from kinocut.ai_engine import transcribe_longform as facade
from kinocut.ai_engine._longform_merge import _merge_chunk
from kinocut.ai_engine._longform_models import LongformChunk, LongformTranscribePlan, LongformWord
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_LONGFORM_TRANSCRIBE_CHUNKS


def _chunk(index, start, end):
    return LongformChunk(index=index, start=start, end=end, duration=end - start)


def _raw(words, start=0, end=2):
    return {
        "segments": [{"text": " ".join(item["word"] for item in words), "start": start, "end": end, "words": words}]
    }


def _word(text, start, end):
    return {"word": text, "start": start, "end": end}


@pytest.mark.parametrize(
    "chunks,duration",
    [
        (tuple(_chunk(index, 0, 1) for index in range(MAX_LONGFORM_TRANSCRIBE_CHUNKS + 1)), 1),
        ((_chunk(0, 0, 40), _chunk(1, 0, 40)), 40),
        ((_chunk(0, 0, 40), _chunk(1, 35, 38), _chunk(2, 35, 60)), 60),
    ],
)
def test_replay_caps_and_nonadvancing_chunks_fail_before_recognizer(monkeypatch, chunks, duration):
    plan = LongformTranscribePlan(
        video_path="source.mp4", duration=duration, chunk_seconds=40, overlap_seconds=5, chunks=chunks
    )
    monkeypatch.setattr(facade, "_validate_longform_path", lambda path: path)
    monkeypatch.setattr(facade, "_get_video_duration", lambda path: duration)
    monkeypatch.setattr(facade, "_transcribe_chunk", lambda *args, **kwargs: pytest.fail("No model may run"))
    with pytest.raises(MCPVideoError) as error:
        facade.transcribe_longform("source.mp4", plan=plan)
    assert error.value.code == "invalid_plan"


@pytest.mark.parametrize("field,value", [("duration", float("nan")), ("chunk_seconds", 0)])
def test_replay_revalidates_unchecked_model_copy_fields(field, value):
    plan = LongformTranscribePlan(
        video_path="source.mp4", duration=1, chunk_seconds=40, overlap_seconds=5, chunks=(_chunk(0, 0, 1),)
    )
    with pytest.raises(MCPVideoError) as error:
        facade._validate_replay_plan("source.mp4", plan.model_copy(update={field: value}), verify_media=False)
    assert error.value.code == "invalid_plan"


@pytest.mark.parametrize("repeat_start,repeat_end", [(0.3, 0.4), (0.8, 1.0)])
def test_same_token_at_distinct_nonoverlapping_event_survives(repeat_start, repeat_end):
    words = [LongformWord(word="yes", start=5.1, end=5.2, chunk_index=0)]
    _merge_chunk(words, [], _raw([_word("yes", repeat_start, repeat_end)]), _chunk(1, 5, 10), 2, 7)
    assert len(words) == 2
    assert words[1].start == 5 + repeat_start


def test_one_prior_event_can_remove_only_one_overlapping_decode_event():
    words = [LongformWord(word="yes", start=5.1, end=5.2, chunk_index=0)]
    _merge_chunk(words, [], _raw([_word("YES", 0.1, 0.2), _word("yes", 0.11, 0.21)]), _chunk(1, 5, 10), 2, 7)
    assert len(words) == 2
    assert words[1].start == 5.11


def test_repeated_sequence_matches_individual_observed_occurrences_once():
    words = [
        LongformWord(word="go", start=5.1, end=5.2, chunk_index=0),
        LongformWord(word="go", start=5.5, end=5.6, chunk_index=0),
    ]
    _merge_chunk(
        words, [], _raw([_word("go", 0.1, 0.2), _word("go", 0.5, 0.6), _word("go", 0.8, 1.0)]), _chunk(1, 5, 10), 2, 7
    )
    assert [(word.start, word.end) for word in words] == [(5.1, 5.2), (5.5, 5.6), (5.8, 6.0)]


def test_small_jitter_duplicate_matches_but_wide_ambiguous_span_does_not():
    words = [LongformWord(word="yes", start=5.1, end=5.5, chunk_index=0)]
    _merge_chunk(words, [], _raw([_word("YES", 0.15, 0.55)]), _chunk(1, 5, 10), 2, 7)
    assert len(words) == 1
    _merge_chunk(words, [], _raw([_word("yes", 0.4, 1.0)]), _chunk(1, 5, 10), 2, 7)
    assert len(words) == 2


@pytest.mark.parametrize("start,end", [(-0.1, 1), (0, 5.001), (float("nan"), 1), (0, float("inf")), (2, 1)])
@pytest.mark.parametrize("kind", ["segment", "word"])
def test_hallucinated_bounds_are_structured_and_merge_is_not_partially_mutated(start, end, kind):
    words, segments = [], []
    invalid = (
        _raw([_word("spoken", 0.1, 0.5)], start=start, end=end)
        if kind == "segment"
        else (_raw([_word("spoken", start, end)]))
    )
    raw = {"segments": [*_raw([_word("valid", 0, 0.1)])["segments"], *invalid["segments"]]}
    before = deepcopy(raw)
    with pytest.raises(MCPVideoError) as error:
        _merge_chunk(words, segments, raw, _chunk(1, 5, 10), 2, 7)
    assert error.value.code == "invalid_transcript_timing"
    assert error.value.suggested_action["entry_kind"] == kind
    assert words == [] and segments == []
    # NaN equality is not reliable, but no keys or nested values were replaced.
    assert raw["segments"][0] == before["segments"][0]


def test_valid_word_at_source_end_remains_exactly_measured():
    words, segments = [], []
    _merge_chunk(words, segments, _raw([_word("last", 4.8, 5.0)], start=4.8, end=5.0), _chunk(1, 5, 10), 2, 7)
    assert words[0].end == segments[0].end == 10


def test_legitimate_partial_overlap_trims_only_observed_prefix_and_discloses_it():
    words = [
        LongformWord(word="first", start=9, end=9.8, chunk_index=0),
        LongformWord(word="next", start=9.6, end=10, chunk_index=1),
    ]
    adjustments = facade._enforce_monotonic_words(words)
    assert (words[1].start, words[1].end) == (9.8, 10)
    assert adjustments[0].original_start == 9.6
    assert adjustments[0].observed_end == 10
    assert adjustments[0].trimmed_start == 9.8


def test_fully_covered_distinct_word_fails_instead_of_inventing_time_after_source_end():
    words = [
        LongformWord(word="first", start=9.5, end=10, chunk_index=0),
        LongformWord(word="distinct", start=9.6, end=9.9, chunk_index=1),
    ]
    with pytest.raises(MCPVideoError) as error:
        facade._enforce_monotonic_words(words)
    assert error.value.code == "invalid_transcript_timing"
    assert words[1].end == 9.9


@pytest.mark.parametrize("raw", [None, [], {"segments": 7}, {"segments": "wrong"}, {"segments": [{"words": 7}]}])
def test_malformed_backend_collections_are_structured_at_format_and_merge(raw):
    from kinocut.ai_engine._longform_runtime import _format_chunk_result

    for operation in (lambda: _format_chunk_result(raw), lambda: _merge_chunk([], [], raw, _chunk(0, 0, 10), 0, None)):
        with pytest.raises(MCPVideoError) as error:
            operation()
        assert error.value.code == "invalid_transcript_output"


@pytest.mark.parametrize("value", [10**1000, True])
@pytest.mark.parametrize("kind", ["segment", "word"])
def test_overflow_and_boolean_claimed_timestamps_are_structured(value, kind):
    raw = _raw([_word("spoken", 0, 1)])
    entry = raw["segments"][0] if kind == "segment" else raw["segments"][0]["words"][0]
    entry["start"] = value
    with pytest.raises(MCPVideoError) as error:
        _merge_chunk([], [], raw, _chunk(0, 0, 10), 0, None)
    assert error.value.code == "invalid_transcript_timing"


@pytest.mark.parametrize("value", [10**1000, True])
def test_unusable_confidence_is_unknown_instead_of_crashing_or_inventing(value):
    from kinocut.ai_engine._longform_merge import _segment_avg_logprob, _segment_no_speech_prob, _word_probability

    assert _word_probability({"probability": value}) is None
    assert _word_probability({"avg_logprob": value}) is None
    assert _segment_avg_logprob({"avg_logprob": value}) is None
    assert _segment_no_speech_prob({"no_speech_prob": value}) is None
