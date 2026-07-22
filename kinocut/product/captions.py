"""Phrase-grouped caption artifacts for the long-form stream-to-shorts workflow.

The captions layer is the bridge between per-word timing (emitted by the
long-form transcription slice) and the editable SRT/VTT assets downstream
reviewers and the workflow render op cursor consume. It is a *pure* helper:

* No engine import — FFmpeg stays in the workflow ``burn_in`` op adapter.
* No I/O — the orchestrator owns disk writes; this module returns strict
  models and plain JSON-serialisable plans.
* No text invention — low-confidence words are either omitted from the cue
  text (the cue's word list still records their timing + probability) or
  flagged with the canonical ``[?]`` placeholder. Reviewers see exactly what
  the ASR emitted; nothing is hallucinated to paper over an unknown.

The phrase-grouping rule is deliberately simple and deterministic:

* Words are concatenated into phrases until either (a) the running character
  budget would exceed ``max_chars_per_phrase``, (b) a clause-terminal
  punctuation mark (``.``, ``!``, ``?``) closes the buffer, or (c) the gap to
  the next word exceeds ``max_gap_seconds``. Whichever rule fires first ends
  the phrase; ties (e.g. punctuation exactly at the boundary) resolve to
  phrase end so the next word starts a fresh cue.
* Per-word confidence is preserved on the resulting :class:`PhraseCue.words`
  tuple so reviewers can edit, regenerate, or apply a different policy
  without re-running transcription.
* Empty-word buffers (e.g. all words dropped under the omit policy) collapse
  to an empty ``warnings`` entry rather than being emitted as zero-width
  cues.

The optional :class:`BurnInPlan` is a *drafting* artefact only: it never
executes FFmpeg. The render op cursor (``kinocut.workflow.ops.burn_in``) is
the only path that may actually burn subtitles into a video, and the plan's
``safe_area`` field carries the normalised ``[0, 1]`` exclusion zones the
reviewer agreed to so the burn-in call inherits them without re-derivation.
The optional :class:`BurnInPlan` is a *drafting* artefact only: it never
executes FFmpeg. The render op cursor (``kinocut.workflow.ops.burn_in``) is
the only path that may actually burn subtitles into a video, and the plan's
``safe_area`` field carries the normalised ``[0, 1]`` exclusion zones the
reviewer agreed to so the burn-in call inherits them without re-derivation.

Companion clip planning helpers in :mod:`kinocut.product.clip_pipeline` are
library-level pure functions for callers that need a serializable planning
contract; the captions layer does not depend on them and the current
orchestrator does not invoke them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal
from pydantic import Field, ValidationError, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

from ..ffmpeg_helpers import _seconds_to_srt_time
from .models import _StrictModel


# --- Constants -------------------------------------------------------------- #
# Lower bound on each ``SafeArea`` dimension (in unit-frame coordinates).
# Anything below this renders as a degenerate FFmpeg drawbox at the burn-in
# stage; rejecting at the model boundary keeps the workflow ``burn_in`` op
# honest and prevents a reviewer from accidentally authoring an empty strip.
_SAFE_AREA_MIN_DIMENSION = 0.001


# When ``on_low_confidence == "flag"`` we replace each low-confidence token in
# the visible cue text with this canonical placeholder. Reviewers see the
# placeholder and the original token + timing in the per-word metadata, but
# no invented text ever lands in the rendered subtitle.
_LOW_CONF_PLACEHOLDER = "[?]"


# Clause-terminal punctuation shared with the existing highlight discovery
# layer. We intentionally keep this regex ASCII-only: multibyte punctuation
# (e.g. ``.``, ``!``, ``?``) is not produced by the upstream long-form transcription
# emitter contract, and falling back to plain ASCII keeps grouping
# deterministic across locales.
_CLAUSE_TERMINAL_RE = re.compile(r"[.!?](?:[\"'\)\]]+|\.{3})?\s*$")


# Whitespace collapse so two tokens that only differ in spacing collapse to
# the same cue text. We deliberately do NOT strip leading/trailing spaces
# here — that's a render-time concern.
_WHITESPACE_RE = re.compile(r"\s+")


# A ``pattern``-safe identifier for a phrase. Bounded lowercase so the field is
# safe to embed in filenames, log lines, and IPC payloads.
_PHRASE_ID_PATTERN = r"^[a-z][a-z0-9_.]{0,63}$"


LowConfidencePolicy = Literal["omit", "flag"]
"""How to render tokens whose probability is below ``low_confidence_threshold``.

* ``"omit"`` — drop the token from the cue's visible text entirely; the
  per-word metadata still records its timing and probability.
* ``"flag"`` — replace the token in the visible text with ``[?]``. The
  per-word metadata still records the original token and probability so the
  reviewer can fix it.
"""


CaptionCueSource = Literal["asr", "manual"]
"""Provenance tag for a phrase cue so reviewers can tell transcription-derived
cues from hand-authored ones."""


# --- Inputs ----------------------------------------------------------------- #


class WordTiming(_StrictModel):
    """One timed word/token consumed by the caption grouper.

    Mirrors the long-form transcription slice's word shape exactly: ``word``
    is the token text, ``start`` and ``end`` are Whisper-style seconds,
    ``probability`` is the per-token confidence (``None`` when Whisper did
    not emit one). The grouper is forward-compatible with bilingual or
    multi-token entries because ``word`` is treated as opaque text.
    """

    word: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    probability: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_time_range(self) -> WordTiming:
        if self.end <= self.start:
            raise ValueError("word end must be strictly greater than start")
        return self


# --- Phrase cue output ------------------------------------------------------ #


class PhraseCue(_StrictModel):
    """One grouped phrase returned by :func:`build_caption_artifact`.

    ``text`` is what reviewers see (and what the SRT writer emits), exactly
    as produced by the active low-confidence policy. ``words`` is the
    immutable per-word source list — including any words that were dropped
    from the visible text under ``omit`` so reviewers can re-run with a
    different threshold without re-transcribing.
    """

    cue_index: int = Field(ge=0)
    phrase_id: str = Field(pattern=_PHRASE_ID_PATTERN)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    text: str = Field(min_length=0)
    words: tuple[WordTiming, ...]
    source: CaptionCueSource = "asr"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_invariants(self) -> PhraseCue:
        if self.end <= self.start:
            raise ValueError("phrase cue end must be strictly greater than start")
        if not self.words:
            raise ValueError("phrase cue must carry at least one word")
        if self.text and not self.text.strip():
            raise ValueError("phrase cue text must be empty when visible, not whitespace")
        return self


# --- SRT writer output ----------------------------------------------------- #


class CaptionArtifact(_StrictModel):
    """The deterministic result of :func:`build_caption_artifact`.

    ``cues`` is the ordered, phrase-grouped cue list. ``srt_body`` is the
    editor-ready SRT body — cue indices, ``HH:MM:SS,mmm`` timestamps, and
    the visible text. ``review_warnings`` collects the human-readable
    warnings the grouper emitted (e.g. ``low_confidence_words``); the
    orchestrator can fan them out to whichever review surface it owns.
    """

    cues: tuple[PhraseCue, ...]
    srt_body: str
    review_warnings: tuple[str, ...]
    low_confidence_policy: LowConfidencePolicy
    low_confidence_threshold: float = Field(ge=0.0, le=1.0)
    dropped_word_count: int = Field(ge=0)
    omitted_token_count: int = Field(ge=0)


# --- Appearance / safe-area placement -------------------------------------- #


class SafeArea(_StrictModel):
    """Normalised caption-safe rectangle for a target platform.

    Every value is in unit-frame coordinates (``[0, 1]``) so the same plan
    round-trips between vertical (9:16) and horizontal (16:9) renders; the
    burn-in op cursor multiplies by ``main_w``/``main_h`` at execution time.
    The rectangle must stay inside the unit frame and carry positive area;
    zero-area rectangles are rejected at construction so a later render
    cannot emit a degenerate FFmpeg expression.
    """

    left: float = Field(ge=0.0, lt=1.0)
    right: float = Field(gt=0.0, le=1.0)
    top: float = Field(ge=0.0, lt=1.0)
    bottom: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_rectangle(self) -> SafeArea:
        if self.right <= self.left:
            raise ValueError("safe_area right must be strictly greater than left")
        if self.bottom <= self.top:
            raise ValueError("safe_area bottom must be strictly greater than top")
        if (self.right - self.left) < _SAFE_AREA_MIN_DIMENSION:
            raise ValueError(f"safe_area width must be at least {_SAFE_AREA_MIN_DIMENSION} in unit-frame coordinates")
        if (self.bottom - self.top) < _SAFE_AREA_MIN_DIMENSION:
            raise ValueError(f"safe_area height must be at least {_SAFE_AREA_MIN_DIMENSION} in unit-frame coordinates")
        return self


class CaptionAppearance(_StrictModel):
    """Visual style for an authored SRT burn-in.

    ``font_size`` is in pixels at the *target* output resolution — not the
    source — so the plan records the intent without dragging the source
    dimensions across the workflow boundary. ``primary_colour``/``outline``
    accept the same ``&HAABBGGRR`` / ``&HBBGGRR`` form FFmpeg consumes via
    ``force_style``; ``alignment`` is the ASS-style numeric code (1..9,
    numpad layout) deliberately shared between this layer and the burn-in
    op adapter.
    """

    font_size: int = Field(default=28, ge=8, le=240)
    primary_colour: str = Field(default="&H00FFFFFF", min_length=1)
    outline: str = Field(default="&H00000000", min_length=1)
    alignment: int = Field(default=2, ge=1, le=9)
    margin_x: int = Field(default=24, ge=0, le=4096)
    margin_y: int = Field(default=64, ge=0, le=4096)


class BurnInPlan(_StrictModel):
    """Drafting-only burn-in plan consumed by the workflow ``burn_in`` op.

    ``enabled=False`` means *do not* emit any ``burn_in`` step; the
    orchestrator simply skips the burn-in rendering. The plan is a *plain
    JSON object*: no callable references, no engine objects, no I/O. Its
    ``safe_area`` always lives with the plan so the burn-in op cursor never
    has to re-derive placement from the source resolution.
    """

    enabled: bool = False
    appearance: CaptionAppearance | None = None
    safe_area: SafeArea | None = None

    @model_validator(mode="after")
    def _validate_plan(self) -> BurnInPlan:
        if self.enabled and self.appearance is None:
            raise ValueError("burn_in.appearance is required when burn_in.enabled is true")
        if self.enabled and self.safe_area is None:
            raise ValueError("burn_in.safe_area is required when burn_in.enabled is true")
        return self


# --- Top-level config ------------------------------------------------------ #


class CaptionConfig(_StrictModel):
    """All knobs the caption grouper accepts at construction.

    Defaults target short-form vertical captions (Shorts/Reels): 18-word
    cues (~ 2 lines at 28 px), 0.6 s inter-word gap, low-confidence words
    *flagged* (visible to the reviewer as ``[?]``) at the conventional
    Whisper 0.5 probability threshold. Every knob is overridable so a
    downstream agent can re-tune without rewriting the policy.
    """

    max_chars_per_phrase: int = Field(default=64, ge=8, le=240)
    max_words_per_phrase: int = Field(default=18, ge=1, le=64)
    max_gap_seconds: float = Field(default=0.6, gt=0.0)
    low_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    low_confidence_policy: LowConfidencePolicy = "flag"
    burn_in: BurnInPlan = Field(default_factory=BurnInPlan)


# --- Helpers exposed for tests and downstream consumers ------------------- #


def _is_clause_terminal(text: str) -> bool:
    """True when ``text`` ends with ``.``/``!``/``?`` (with optional closing
    quote/bracket and trailing whitespace). Used by the grouper to end a
    phrase exactly at sentence boundaries.
    """

    return bool(_CLAUSE_TERMINAL_RE.search(text))


def _normalise_visible_whitespace(text: str) -> str:
    """Collapse runs of whitespace in the visible cue text.

    A leading or trailing space is preserved *only* when it was already
    present in the source words — collapsing it would shift the visible
    text relative to the per-word metadata, which reviewers depend on.
    """

    leading = len(text) - len(text.lstrip(" "))
    trailing = len(text) - len(text.rstrip(" "))
    inner = _WHITESPACE_RE.sub(" ", text.strip())
    return (" " * leading) + inner + (" " * trailing)


def _visible_text_for_word(
    word: WordTiming,
    *,
    threshold: float,
    policy: LowConfidencePolicy,
) -> str:
    """Render one word's contribution to the visible cue text.

    Under ``"omit"`` a low-confidence token yields the empty string; the
    per-word metadata still records it. Under ``"flag"`` it yields the
    canonical ``[?]`` placeholder so the reviewer sees *something* is
    wrong at that timestamp but the original token is not invented.
    """

    prob = word.probability
    if prob is not None and prob < threshold:
        return "" if policy == "omit" else _LOW_CONF_PLACEHOLDER
    return word.word


def _cue_confidence(words: Sequence[WordTiming]) -> float | None:
    """Mean per-word probability, ignoring tokens that did not declare one.

    Returns ``None`` when every word omitted its probability so the caption
    layer never silently rates manually-authored cues as 100% confident —
    that would mislead the review surface and mask upstream silence.
    Reviewers who need a numeric confidence for an unknown-probability cue
    must supply it explicitly via a downstream re-derivation; the grouper
    refuses to invent one.
    """

    probs = [w.probability for w in words if w.probability is not None]
    if not probs:
        return None
    return sum(probs) / len(probs)


def _phrase_id(cue_index: int) -> str:
    """Stable, bounded, sortable phrase identifier for a cue index."""

    return f"cue_{cue_index:04d}"


# --- SRT body builder ------------------------------------------------------ #


def build_srt_body(cues: Sequence[PhraseCue]) -> str:
    """Render the ordered cue list as an SRT body.

    Empty cues (zero-character visible text, e.g. after dropping every
    low-confidence word under ``"omit"``) are *omitted from the SRT body*
    rather than emitted as zero-width cues; their per-word metadata still
    lives on the model so reviewers can re-tune and regenerate.
    """

    blocks: list[str] = []
    serial = 0
    for cue in cues:
        if not cue.text:
            continue
        serial += 1
        blocks.append(str(serial))
        blocks.append(f"{_seconds_to_srt_time(cue.start)} --> {_seconds_to_srt_time(cue.end)}")
        blocks.append(_normalise_visible_whitespace(cue.text))
        blocks.append("")
    return "\n".join(blocks)


# --- Grouping --------------------------------------------------------------- #


def _group_words(
    words: Sequence[WordTiming],
    *,
    config: CaptionConfig,
) -> tuple[list[list[WordTiming]], list[str], int]:
    """Group raw words into phrase buffers under the active policy.

    Returns ``(phrases, warnings, dropped_total)``. ``dropped_total`` counts
    words that were *entirely omitted* from the visible text (only under
    ``"omit"`` — flagged words remain visible as ``[?]``). Empty phrases
    that contain only omitted words are dropped from the returned list so
    the cue layer never emits zero-width cues.
    """

    phrases: list[list[WordTiming]] = []
    warnings: list[str] = []
    dropped_phrase_total = 0
    buffer: list[WordTiming] = []
    buffer_chars = 0
    buffer_words = 0

    def _flush() -> int:
        nonlocal buffer, buffer_chars, buffer_words
        if not buffer:
            return 0
        # Compute the visible text for this buffer before moving on; the
        # caller keeps the original word list on the cue.
        rendered, _dropped_in_phrase = _render_buffer_text(buffer, config=config)
        if rendered.strip():
            phrases.append(list(buffer))
        else:
            # Every word in the buffer was dropped; audit how much signal
            # was lost so downstream reviewers can re-tune the threshold.
            dropped_phrase_local = len(buffer)
        buffer = []
        buffer_chars = 0
        buffer_words = 0
        if rendered.strip():
            return 0
        return dropped_phrase_local

    for word in words:
        next_word_chars = len(
            _visible_text_for_word(
                word,
                threshold=config.low_confidence_threshold,
                policy=config.low_confidence_policy,
            )
        )
        next_word_chars = max(next_word_chars, len(word.word))

        if buffer:
            gap = word.start - buffer[-1].end
            end_phrase = (
                (buffer_chars + next_word_chars) > config.max_chars_per_phrase
                or (buffer_words + 1) > config.max_words_per_phrase
                or gap > config.max_gap_seconds
            )
            if end_phrase:
                flush_count = _flush()
                if flush_count:
                    dropped_phrase_total += flush_count
                    warnings.append("low_confidence_words_dropped_phrase")

        if not buffer:
            buffer.append(word)
            buffer_chars = next_word_chars
            buffer_words = 1
        else:
            buffer.append(word)
            buffer_chars += 1 + next_word_chars  # include the joining space
            buffer_words += 1

        # ``_is_clause_terminal`` checks the *original* token text rather
        # than the rendered placeholder, so the ``[?]`` flag literal never
        # collides with the trailing-``]`` branch of the clause regex.
        if _is_clause_terminal(word.word + (" " if config.low_confidence_policy == "omit" else "")):
            flush_count = _flush()
            if flush_count:
                dropped_phrase_total += flush_count
                warnings.append("low_confidence_words_dropped_phrase")

    flush_count = _flush()
    if flush_count:
        dropped_phrase_total += flush_count
        warnings.append("low_confidence_words_dropped_phrase")
    return phrases, warnings, dropped_phrase_total


def _render_buffer_text(
    buffer: Sequence[WordTiming],
    *,
    config: CaptionConfig,
) -> tuple[str, int]:
    """Render a phrase buffer to its visible text + a count of dropped tokens.

    Tokens whose probability is below threshold yield either ``""`` (omit)
    or ``[?]`` (flag). The ``dropped`` counter only counts *omitted*
    tokens — flagged tokens remain on screen, so reviewing them is just a
    visual scan.
    """

    rendered_parts: list[str] = []
    dropped = 0
    for word in buffer:
        visible = _visible_text_for_word(
            word,
            threshold=config.low_confidence_threshold,
            policy=config.low_confidence_policy,
        )
        if visible == "" and (word.probability is not None and word.probability < config.low_confidence_threshold):
            dropped += 1
            continue
        rendered_parts.append(visible)
    return " ".join(rendered_parts), dropped


# --- Public API ------------------------------------------------------------ #


def build_caption_artifact(
    words: Iterable[WordTiming | Mapping[str, Any]],
    *,
    config: CaptionConfig | None = None,
) -> CaptionArtifact:
    """Group timed words into phrases and emit a :class:`CaptionArtifact`.

    The input may be a sequence of strict :class:`WordTiming` *or* a
    mapping-shaped dict (e.g. a freshly-decoded JSON payload from the
    long-form transcription slice) carrying the same four fields. Mapping
    inputs are coerced to strict models first so downstream code never has
    to deal with the heterogeneous shape.

    Phrasing follows :class:`CaptionConfig`; the SRT body omits empty cues
    but preserves them on ``artifact.cues`` so reviewers can audit what
    happened to every dropped segment.
    """

    cfg = config or CaptionConfig()
    if not isinstance(cfg, CaptionConfig):
        # Construct from a Mapping for parity with the rest of the slice.
        cfg = CaptionConfig.model_validate(cfg)

    normalized = [_coerce_word(item) for item in words]
    if not normalized:
        raise ValidationError.from_exception_data(
            "build_caption_artifact",
            [
                InitErrorDetails(
                    type=PydanticCustomError(
                        "value_error",
                        "cannot build a caption artifact from zero words",
                    ),
                    loc=("words",),
                    input=[],
                ),
            ],
        )

    phrases, grouping_warnings, dropped_total = _group_words(normalized, config=cfg)
    if not phrases:
        raise ValueError(
            "every word was dropped by the low-confidence policy; "
            "lower low_confidence_threshold or change low_confidence_policy"
        )

    cues: list[PhraseCue] = []
    omitted_token_count = 0
    for index, buffer in enumerate(phrases):
        visible_text, dropped = _render_buffer_text(buffer, config=cfg)
        omitted_token_count += dropped
        cue = PhraseCue(
            cue_index=index,
            phrase_id=_phrase_id(index),
            start=buffer[0].start,
            end=buffer[-1].end,
            text=visible_text,
            words=tuple(buffer),
            source="asr",
            confidence=_cue_confidence(buffer),
        )
        cues.append(cue)

    review_warnings: list[str] = []
    if cfg.low_confidence_policy == "omit" and omitted_token_count:
        review_warnings.append("low_confidence_words")
    elif cfg.low_confidence_policy == "flag":
        review_warnings.append("low_confidence_words_flagged")
    for warning in grouping_warnings:
        if warning not in review_warnings:
            review_warnings.append(warning)

    return CaptionArtifact(
        cues=tuple(cues),
        srt_body=build_srt_body(cues),
        review_warnings=tuple(review_warnings),
        low_confidence_policy=cfg.low_confidence_policy,
        low_confidence_threshold=cfg.low_confidence_threshold,
        dropped_word_count=dropped_total,
        omitted_token_count=omitted_token_count,
    )


def _coerce_word(item: WordTiming | Mapping[str, Any]) -> WordTiming:
    if isinstance(item, WordTiming):
        return item
    if isinstance(item, Mapping):
        return WordTiming.model_validate(item)
    raise TypeError(f"expected a WordTiming or Mapping[str, Any], got {type(item).__name__}")


__all__ = [
    "BurnInPlan",
    "CaptionAppearance",
    "CaptionArtifact",
    "CaptionConfig",
    "CaptionCueSource",
    "LowConfidencePolicy",
    "PhraseCue",
    "SafeArea",
    "WordTiming",
    "build_caption_artifact",
    "build_srt_body",
]
