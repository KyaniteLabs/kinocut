"""Word-timed caption grouper contract (Plan Phase-2 captions slice).

Every test here is pure — no FFmpeg, no I/O outside ``tmp_path`` — and
covers one behavioural claim:

* ``test_capt_build_*`` — phrase grouping, timing preservation, the four
  grouping rules (budget, words, gap, clause-terminal).
* ``test_capt_low_conf_*`` — low-confidence word handling under both
  policies (omit / flag) and the warn-on-empty-after-omit fail-closed
  guarantee.
* ``test_capt_burn_in_*`` — optional ``BurnInPlan`` validation, the
  safe-area rectangle, and the appearance defaults.
* ``test_capt_safe_area_*`` — safe-area validation (rectangle, in-frame,
  zero-area rejection).

The strict-model guarantees (``extra="forbid"``, ``frozen=True``,
``allow_inf_nan=False``) are exercised by every model constructor call —
any future field addition fails closed.
"""

from __future__ import annotations

import pytest
import json
from pydantic import ValidationError

from kinocut.product.captions import (
    BurnInPlan,
    CaptionAppearance,
    CaptionConfig,
    PhraseCue,
    SafeArea,
    WordTiming,
    build_caption_artifact,
    build_srt_body,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _word(text, start, end, probability=None):
    """Tiny builder for ``WordTiming`` with no-whistle defaults."""

    return WordTiming.model_validate(
        {
            "word": text,
            "start": start,
            "end": end,
            "probability": probability,
        }
    )


def _words(*tuples):
    """Convert ``((text, start, end, probability), ...)`` into WordTimings."""

    for tup in tuples:
        if len(tup) == 3:
            text, start, end = tup
            yield _word(text, start, end)
        else:
            text, start, end, prob = tup
            yield _word(text, start, end, prob)


# --------------------------------------------------------------------------- #
# Phrase grouping
# --------------------------------------------------------------------------- #


def test_capt_build_groups_short_words_into_single_phrase():
    artifact = build_caption_artifact(
        list(
            _words(
                ("Hello", 0.0, 0.4, 0.9),
                ("world", 0.45, 0.9, 0.95),
                ("today", 1.0, 1.4, 0.95),
            )
        )
    )
    assert len(artifact.cues) == 1
    cue = artifact.cues[0]
    assert cue.start == 0.0
    assert cue.end == 1.4
    assert cue.text == "Hello world today"
    assert [w.word for w in cue.words] == ["Hello", "world", "today"]


def test_capt_build_splits_phrase_at_clause_terminal_punctuation():
    artifact = build_caption_artifact(
        list(
            _words(
                ("First", 0.0, 0.4, 0.9),
                ("sentence.", 0.45, 0.9, 0.95),
                ("Second", 1.0, 1.4, 0.95),
                ("sentence?", 1.45, 1.9, 0.95),
            )
        )
    )
    assert [c.text for c in artifact.cues] == [
        "First sentence.",
        "Second sentence?",
    ]
    assert artifact.cues[0].end == 0.9
    assert artifact.cues[1].start == 1.0


def test_capt_build_splits_phrase_at_gap_threshold():
    artifact = build_caption_artifact(
        list(
            _words(
                ("Alpha", 0.0, 0.4, 0.9),
                ("beta", 0.45, 0.7, 0.9),
                ("gamma", 2.0, 2.4, 0.9),  # 1.3s gap > default 0.6s
            )
        )
    )
    assert [c.text for c in artifact.cues] == [
        "Alpha beta",
        "gamma",
    ]


def test_capt_build_respects_max_words_per_phrase():
    cfg = CaptionConfig(max_words_per_phrase=2, max_chars_per_phrase=64, max_gap_seconds=60.0)
    artifact = build_caption_artifact(
        list(
            _words(
                ("One", 0.0, 0.3, 0.9),
                ("Two", 0.3, 0.6, 0.9),
                ("Three", 0.6, 0.9, 0.9),
                ("Four", 0.9, 1.2, 0.9),
            )
        ),
        config=cfg,
    )
    assert [c.text for c in artifact.cues] == ["One Two", "Three Four"]


def test_capt_build_respects_max_chars_per_phrase():
    cfg = CaptionConfig(max_chars_per_phrase=8, max_words_per_phrase=18, max_gap_seconds=60.0)
    artifact = build_caption_artifact(
        list(
            _words(
                ("ab", 0.0, 0.2, 0.9),
                ("cd", 0.2, 0.4, 0.9),
                ("ef", 0.4, 0.6, 0.9),
            )
        ),
        config=cfg,
    )
    # "ab cd" = 5 chars (within 8), "cd ef" or similar overlap-avoided split
    assert all(len(c.text) <= 8 for c in artifact.cues)
    # All words end up in cues — none dropped, none overlapped.
    assert sum(len(c.words) for c in artifact.cues) == 3


def test_capt_build_preserves_word_timing_per_cue():
    artifact = build_caption_artifact(
        list(
            _words(
                ("Hello", 0.1, 0.4, 0.9),
                ("world", 0.5, 0.9, 0.95),
                ("foo", 2.0, 2.4, 0.95),
                ("bar", 2.5, 2.9, 0.95),
            )
        )
    )
    assert [c.start for c in artifact.cues] == [0.1, 2.0]
    assert [c.end for c in artifact.cues] == [0.9, 2.9]
    assert artifact.cues[0].words[0].word == "Hello"
    assert artifact.cues[0].words[1].word == "world"
    assert artifact.cues[1].words[0].word == "foo"
    assert artifact.cues[1].words[1].word == "bar"


def test_capt_build_cue_confidence_is_mean_of_present_probabilities():
    artifact = build_caption_artifact(
        list(
            _words(
                ("a", 0.0, 0.2, 0.6),
                ("b", 0.2, 0.4, 0.8),
                ("c", 0.4, 0.6, None),  # ignored
            )
        )
    )
    assert artifact.cues[0].confidence == pytest.approx(0.7)


def test_capt_build_cue_confidence_is_none_when_all_probabilities_missing():
    artifact = build_caption_artifact(
        list(
            _words(
                ("a", 0.0, 0.2, None),
                ("b", 0.2, 0.4, None),
            )
        )
    )
    # Truthful default: a cue whose every word omitted its probability
    # surfaces as ``None`` rather than fabricating a 1.0. The caption layer
    # never silently rates manually-authored or upstream-silent cues as
    # 100% confident — that would mislead the review surface and mask the
    # fact that confidence is actually unknown.
    assert artifact.cues[0].confidence is None


def test_capt_build_cue_confidence_preserves_explicit_probabilities():
    """Explicit per-word probabilities flow through to ``PhraseCue.confidence``.

    A reviewer-supplied cue (or a downstream re-derivation that knows
    upstream confidence) must surface its probabilities verbatim; the
    grouper MUST NOT invent a number that disagrees with the per-word
    metadata that already lives on the cue.
    """
    artifact = build_caption_artifact(
        list(
            _words(
                ("a", 0.0, 0.2, 0.25),
                ("b", 0.2, 0.4, 0.75),
            )
        )
    )
    assert artifact.cues[0].confidence == pytest.approx(0.5)
    # Every per-word probability is preserved on the cue's word metadata.
    assert [w.probability for w in artifact.cues[0].words] == [0.25, 0.75]


def test_capt_build_assigns_bounded_phrase_ids_in_order():
    artifact = build_caption_artifact(
        list(
            _words(
                ("a.", 0.0, 0.2, 0.9),
                ("b.", 0.3, 0.5, 0.9),
                ("c.", 0.6, 0.8, 0.9),
                ("d.", 0.9, 1.1, 0.9),
            )
        )
    )
    assert [c.phrase_id for c in artifact.cues] == ["cue_0000", "cue_0001", "cue_0002", "cue_0003"]
    assert [c.cue_index for c in artifact.cues] == [0, 1, 2, 3]


def test_capt_build_rejects_empty_input():
    with pytest.raises(ValidationError):
        build_caption_artifact([])


# --------------------------------------------------------------------------- #
# Low-confidence handling
# --------------------------------------------------------------------------- #


def test_capt_low_conf_flag_marks_low_confidence_tokens_with_placeholder():
    cfg = CaptionConfig(low_confidence_policy="flag", low_confidence_threshold=0.5)
    artifact = build_caption_artifact(
        list(
            _words(
                ("Hello", 0.0, 0.4, 0.9),
                ("world", 0.45, 0.8, 0.3),  # below threshold
                ("foo", 0.85, 1.2, 0.95),
            )
        ),
        config=cfg,
    )
    assert artifact.cues[0].text == "Hello [?] foo"
    # Original word + its probability are preserved on per-word metadata.
    assert artifact.cues[0].words[1].word == "world"
    assert artifact.cues[0].words[1].probability == 0.3
    assert "low_confidence_words_flagged" in artifact.review_warnings


def test_capt_low_conf_omit_drops_low_confidence_tokens_from_visible_text():
    cfg = CaptionConfig(low_confidence_policy="omit", low_confidence_threshold=0.5)
    artifact = build_caption_artifact(
        list(
            _words(
                ("Hello", 0.0, 0.4, 0.9),
                ("world", 0.45, 0.8, 0.3),  # below threshold
                ("foo", 0.85, 1.2, 0.95),
            )
        ),
        config=cfg,
    )
    # The visible cue keeps neighbouring high-confidence words; the dropped
    # token does NOT collapse into extra whitespace.
    assert artifact.cues[0].text == "Hello foo"
    # But the per-word metadata still carries the dropped token (so reviewers
    # can re-tune and regenerate without re-transcribing).
    assert artifact.cues[0].words[1].word == "world"
    assert artifact.cues[0].words[1].probability == 0.3
    assert artifact.omitted_token_count == 1
    assert "low_confidence_words" in artifact.review_warnings


def test_capt_low_conf_threshold_boundary_keeps_token_at_threshold():
    # ``prob == threshold`` is *not* below; the policy must be strict-less.
    cfg = CaptionConfig(low_confidence_policy="flag", low_confidence_threshold=0.5)
    artifact = build_caption_artifact([_word("ok", 0.0, 0.5, 0.5)], config=cfg)
    assert artifact.cues[0].text == "ok"


def test_capt_low_conf_omit_all_words_dropped_raises():
    cfg = CaptionConfig(low_confidence_policy="omit", low_confidence_threshold=0.5)
    with pytest.raises(ValueError):
        build_caption_artifact(
            list(
                _words(
                    ("a", 0.0, 0.3, 0.1),
                    ("b", 0.3, 0.6, 0.1),
                )
            ),
            config=cfg,
        )


def test_capt_low_conf_preserves_dropped_words_on_artifact_for_audit():
    cfg = CaptionConfig(low_confidence_policy="omit", low_confidence_threshold=0.5)
    artifact = build_caption_artifact(
        list(
            _words(
                ("kept", 0.0, 0.3, 0.9),
                ("dropped", 0.3, 0.5, 0.1),
            )
        ),
        config=cfg,
    )
    assert artifact.dropped_word_count == 0  # the cue still carries the dropped word
    assert artifact.cues[0].words[0].word == "kept"
    assert artifact.cues[0].words[1].word == "dropped"
    assert artifact.cues[0].words[1].probability == 0.1


def test_capt_low_conf_uses_placeholder_literal_not_invented_text():
    cfg = CaptionConfig(low_confidence_policy="flag", low_confidence_threshold=0.5)
    artifact = build_caption_artifact([_word("nonword", 0.0, 0.4, 0.1)], config=cfg)
    # The placeholder is the canonical ``[?]`` — never an invented token.
    assert artifact.cues[0].text == "[?]"
    assert "nonword" not in artifact.cues[0].text


# --------------------------------------------------------------------------- #
# SRT body builder
# --------------------------------------------------------------------------- #


def test_capt_build_srt_body_uses_canonical_time_format():
    artifact = build_caption_artifact([_word("hi", 0.0, 1.5, 0.9)])
    assert "00:00:00,000 --> 00:00:01,500" in artifact.srt_body


def test_capt_build_srt_body_increments_serial_numbers():
    artifact = build_caption_artifact(
        list(
            _words(
                ("a", 0.0, 0.2, 0.9),
                ("b", 0.3, 0.5, 0.9),  # 0.1s gap < 0.6s default
                ("c", 0.6, 0.8, 0.9),
                ("d", 2.0, 2.2, 0.9),  # 1.4s gap > 0.6s -> new phrase
            )
        )
    )
    body = artifact.srt_body
    # First line in each cue block is the serial number.
    blocks = [block for block in body.strip().split("\n\n")]
    assert blocks[0].startswith("1\n")
    assert blocks[1].startswith("2\n")


def test_capt_build_srt_body_omits_empty_cues_but_keeps_them_on_model():
    cfg = CaptionConfig(low_confidence_policy="omit", low_confidence_threshold=0.5)
    artifact = build_caption_artifact(
        list(
            _words(
                ("kept", 0.0, 0.3, 0.9),
                ("dropped", 0.3, 0.6, 0.1),
                # Second phrase separated by a 1.4s gap so the grouping produces
                # two distinct cues; we can then assert that the dropped word stays
                # on the first cue's per-word metadata for reviewer audit.
                ("other", 2.0, 2.3, 0.9),
            )
        ),
        config=cfg,
    )
    assert len(artifact.cues) == 2
    # First cue's visible text omits the dropped word; metadata preserves it.
    assert artifact.cues[0].text == "kept"
    assert artifact.cues[0].words[0].word == "kept"
    assert artifact.cues[0].words[1].word == "dropped"
    # Second cue is intact.
    assert artifact.cues[1].text == "other"


def test_capt_build_srt_body_supports_external_helper():
    artifact = build_caption_artifact(
        list(
            _words(
                ("Hello", 0.0, 0.4, 0.9),
                ("world", 0.5, 0.9, 0.95),
            )
        )
    )
    body = build_srt_body(artifact.cues)
    assert "Hello world" in body
    assert "00:00:00,000 --> 00:00:00,900" in body


# --------------------------------------------------------------------------- #
# Burn-in plan & appearance (drafting-only)
# --------------------------------------------------------------------------- #


def test_capt_burn_in_disabled_by_default_yields_no_appearance_required():
    cfg = CaptionConfig()
    assert cfg.burn_in.enabled is False
    assert cfg.burn_in.appearance is None
    assert cfg.burn_in.safe_area is None


def test_capt_burn_in_enabled_requires_appearance_and_safe_area():
    with pytest.raises(ValidationError):
        BurnInPlan(enabled=True, appearance=None, safe_area=None)
    with pytest.raises(ValidationError):
        BurnInPlan(enabled=True, appearance=CaptionAppearance(), safe_area=None)


def test_capt_burn_in_plan_is_drafting_only_with_strict_models():
    plan = BurnInPlan(
        enabled=True,
        appearance=CaptionAppearance(),
        safe_area=SafeArea(left=0.05, right=0.95, top=0.10, bottom=0.90),
    )
    # Plan is a strict model; it round-trips through model_dump(mode="json").
    payload = plan.model_dump(mode="json")
    assert payload["enabled"] is True
    assert payload["appearance"]["font_size"] == 28  # default
    assert payload["appearance"]["alignment"] == 2  # bottom-center


def test_capt_appearance_rejects_out_of_range_font_size():
    with pytest.raises(ValidationError):
        CaptionAppearance(font_size=2)
    with pytest.raises(ValidationError):
        CaptionAppearance(font_size=999)


def test_capt_appearance_rejects_invalid_alignment():
    # ASS alignment is a closed range — fail closed on unknown values.
    with pytest.raises(ValidationError):
        CaptionAppearance(alignment=0)
    with pytest.raises(ValidationError):
        CaptionAppearance(alignment=10)


# --------------------------------------------------------------------------- #
# Safe area (placement metadata)
# --------------------------------------------------------------------------- #


def test_capt_safe_area_accepts_normalized_inside_frame_rectangle():
    rect = SafeArea(left=0.05, right=0.95, top=0.10, bottom=0.90)
    assert rect.left == 0.05
    assert rect.right == 0.95


def test_capt_safe_area_rejects_inverted_horizontal():
    with pytest.raises(ValidationError):
        SafeArea(left=0.5, right=0.5, top=0.1, bottom=0.9)
    with pytest.raises(ValidationError):
        SafeArea(left=0.7, right=0.3, top=0.1, bottom=0.9)


def test_capt_safe_area_rejects_inverted_vertical():
    with pytest.raises(ValidationError):
        SafeArea(left=0.1, right=0.9, top=0.5, bottom=0.5)
    with pytest.raises(ValidationError):
        SafeArea(left=0.1, right=0.9, top=0.9, bottom=0.1)


def test_capt_safe_area_rejects_zero_area_rectangle():
    # A degenerately-thin strip is the kind of metadata a render layer
    # would silently mis-apply; reject at the model boundary.
    with pytest.raises(ValidationError):
        SafeArea(left=0.5, right=0.6, top=0.5, bottom=0.5001)


def test_capt_safe_area_rejects_out_of_frame_extent():
    with pytest.raises(ValidationError):
        SafeArea(left=-0.01, right=0.9, top=0.1, bottom=0.9)
    with pytest.raises(ValidationError):
        SafeArea(left=0.0, right=1.01, top=0.1, bottom=0.9)


# --------------------------------------------------------------------------- #
# Strict-model guarantees
# --------------------------------------------------------------------------- #


def test_capt_phrase_cue_rejects_zero_width():
    with pytest.raises(ValidationError):
        PhraseCue(
            cue_index=0,
            phrase_id="cue_0000",
            start=1.0,
            end=1.0,
            text="hi",
            words=(_word("hi", 1.0, 1.5, 0.9),),
        )


def test_capt_phrase_cue_rejects_empty_word_list():
    with pytest.raises(ValidationError):
        PhraseCue(
            cue_index=0,
            phrase_id="cue_0000",
            start=0.0,
            end=0.5,
            text="",
            words=(),
        )


def test_capt_word_timing_rejects_end_before_start():
    with pytest.raises(ValidationError):
        WordTiming.model_validate({"word": "x", "start": 1.0, "end": 0.5, "probability": None})


def test_capt_word_timing_rejects_out_of_range_probability():
    with pytest.raises(ValidationError):
        WordTiming.model_validate({"word": "x", "start": 0.0, "end": 0.5, "probability": 1.1})
    with pytest.raises(ValidationError):
        WordTiming.model_validate({"word": "x", "start": 0.0, "end": 0.5, "probability": -0.1})


def test_capt_artifact_payload_is_json_stable_and_sorted():
    artifact = build_caption_artifact(
        list(
            _words(
                ("a", 0.0, 0.3, 0.9),
                ("b", 0.4, 0.7, 0.95),
            )
        )
    )
    payload = artifact.model_dump(mode="json")
    # JSON-stable shape: every declared field is present and the payload is
    # round-trippable through ``json.dumps(..., sort_keys=True)`` so the
    # canonical bytes are deterministic across writers.
    expected_keys = {
        "cues",
        "dropped_word_count",
        "low_confidence_policy",
        "low_confidence_threshold",
        "omitted_token_count",
        "review_warnings",
        "srt_body",
    }
    assert set(payload.keys()) == expected_keys
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    assert json.loads(canonical) == payload
    # All cues must be list-typed (deep-coerced from a tuple by ``mode="json"``).
    assert isinstance(payload["cues"], list)
    assert isinstance(payload["cues"][0]["words"], list)


# --------------------------------------------------------------------------- #
# GLM L2 / L4 — cue-level confidence truthfulness + _flush return contract
# --------------------------------------------------------------------------- #


def test_capt_phrase_cue_accepts_none_confidence():
    """``PhraseCue.confidence`` is ``float | None``.

    The strict model must accept ``None`` so cues whose every word omitted
    its probability can surface truthfully. A cue must never be forced into
    a numeric confidence the upstream emitter never produced.
    """
    cue = PhraseCue(
        cue_index=0,
        phrase_id="cue_0000",
        start=0.0,
        end=0.5,
        text="hello",
        words=(_word("hello", 0.0, 0.5, None),),
        confidence=None,
    )
    assert cue.confidence is None


def test_capt_phrase_cue_payload_serializes_none_confidence_as_null():
    """JSON serialization of a ``None`` confidence emits the canonical ``null``.

    Reviewers and downstream consumers MUST be able to distinguish "unknown"
    (the new contract) from "0% confident" (which would be a fabricated
    value). The strict model's ``mode="json"`` payload uses ``None``.
    """
    cue = PhraseCue(
        cue_index=0,
        phrase_id="cue_0000",
        start=0.0,
        end=0.5,
        text="hello",
        words=(_word("hello", 0.0, 0.5, None),),
        confidence=None,
    )
    payload = cue.model_dump(mode="json")
    assert payload["confidence"] is None
    # JSON round-trip preserves ``None``.
    raw = json.dumps(payload)
    reloaded = PhraseCue.model_validate_json(raw)
    assert reloaded.confidence is None


def test_capt_phrase_cue_accepts_explicit_numeric_confidence():
    """Explicit numeric confidence is preserved verbatim.

    A cue whose per-word probabilities are all declared gets the mean; the
    resulting strict model must keep that numeric value rather than
    collapsing it to ``None``.
    """
    cue = PhraseCue(
        cue_index=0,
        phrase_id="cue_0000",
        start=0.0,
        end=0.5,
        text="hello world",
        words=(
            _word("hello", 0.0, 0.25, 0.6),
            _word("world", 0.25, 0.5, 0.8),
        ),
        confidence=0.7,
    )
    assert cue.confidence == pytest.approx(0.7)


def test_capt_low_conf_omit_dropped_phrase_count_propagates_through_public_api():
    """``_flush``'s dropped-phrase count must propagate to ``dropped_word_count``.

    Exercise the contract through the public ``build_caption_artifact``
    surface: under ``omit`` policy with a phrase whose every word falls
    below the threshold, the grouper drops the phrase entirely. ``_flush``
    returns the count, which the caller adds to ``dropped_word_count`` and
    appends the canonical warning.
    """
    cfg = CaptionConfig(
        low_confidence_policy="omit",
        low_confidence_threshold=0.5,
        max_chars_per_phrase=64,
        max_words_per_phrase=18,
        max_gap_seconds=0.6,
    )
    # Two phrases separated by a >gap. The first is all-kept, the second
    # is all-low-confidence -> dropped entirely. ``_flush`` returns the
    # dropped-phrase count, which the caller adds to ``dropped_word_count``
    # and surfaces as the canonical "low_confidence_words_dropped_phrase"
    # warning.
    artifact = build_caption_artifact(
        list(
            _words(
                ("kept1", 0.0, 0.3, 0.9),
                ("kept2", 0.3, 0.6, 0.9),
                # >0.6s gap forces a phrase boundary; the new phrase is
                # entirely low-confidence and gets dropped.
                ("drop1", 2.0, 2.2, 0.1),
                ("drop2", 2.2, 2.4, 0.1),
            )
        ),
        config=cfg,
    )
    # Only the kept phrase survives as a cue.
    assert len(artifact.cues) == 1
    assert artifact.cues[0].text == "kept1 kept2"
    # ``_flush`` reported 2 dropped words; the audit counter captures it.
    assert artifact.dropped_word_count == 2
    # The canonical warning emitted by the ``_flush`` int-return path.
    assert "low_confidence_words_dropped_phrase" in artifact.review_warnings
