"""Strict caption timing contracts, deterministic SRT serialization, and safe-placement planner."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise
from typing import Any, Literal

from pydantic import Field, model_validator

from kinocut.contracts._common import ValueObject
from kinocut.ffmpeg_helpers import _seconds_to_srt_time


class WordTiming(ValueObject):
    """One source word with a finite, positive-duration time range."""

    word: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    probability: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_timing(self) -> WordTiming:
        if not self.word.strip():
            raise ValueError("word must contain non-whitespace text")
        if self.end <= self.start:
            raise ValueError("word end must be strictly greater than start")
        return self


class PhraseCue(ValueObject):
    """A visible cue bound exactly to its immutable source-word span."""

    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    text: str = Field(min_length=1)
    words: tuple[WordTiming, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_cue(self) -> PhraseCue:
        if not self.text.strip():
            raise ValueError("cue text must contain non-whitespace text")
        if self.end <= self.start:
            raise ValueError("cue end must be strictly greater than start")
        if self.start != self.words[0].start or self.end != self.words[-1].end:
            raise ValueError("cue must span exactly its first and last source word")
        if any(current.start < previous.end for previous, current in pairwise(self.words)):
            raise ValueError("cue source words must be monotonic and non-overlapping")
        return self


LowConfidencePolicy = Literal["omit", "flag"]


class CaptionConfig(ValueObject):
    """Immutable, bounded phrase-grouping policy."""

    max_words_per_cue: int = Field(default=8, ge=1, le=100)
    max_cue_duration: float = Field(default=4.0, gt=0.0, le=60.0)
    low_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    on_low_confidence: LowConfidencePolicy = "flag"


class CaptionArtifact(ValueObject):
    """Editable phrase cues and their deterministic SRT serialization."""

    cues: tuple[PhraseCue, ...]
    srt_body: str
    warnings: tuple[str, ...]
    low_confidence_token_count: int = Field(ge=0)
    omitted_token_count: int = Field(ge=0)


def build_srt_body(cues: Sequence[PhraseCue]) -> str:
    """Serialize ordered, non-overlapping cues into a stable SRT body."""

    blocks: list[str] = []
    previous_end: float | None = None
    for number, cue in enumerate(cues, start=1):
        if previous_end is not None and cue.start < previous_end:
            raise ValueError("caption cues must be monotonic and non-overlapping")
        blocks.append(f"{number}\n{_seconds_to_srt_time(cue.start)} --> {_seconds_to_srt_time(cue.end)}\n{cue.text}")
        previous_end = cue.end
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def build_caption_artifact(
    words: Iterable[WordTiming | Mapping[str, Any]],
    *,
    config: CaptionConfig | None = None,
) -> CaptionArtifact:
    """Build truthful phrase cues without changing any source timestamp."""

    cfg = config or CaptionConfig()
    normalized = sorted((_coerce_word(item) for item in words), key=lambda word: word.start)
    for previous, current in pairwise(normalized):
        if current.start < previous.end:
            raise ValueError("caption words must be unambiguously ordered and non-overlapping")

    groups: list[list[WordTiming]] = []
    current_group: list[WordTiming] = []
    for word in normalized:
        if word.end - word.start > cfg.max_cue_duration:
            raise ValueError("a source word exceeds max_cue_duration and cannot be split truthfully")
        exceeds_limit = current_group and (
            len(current_group) >= cfg.max_words_per_cue or word.end - current_group[0].start > cfg.max_cue_duration
        )
        if exceeds_limit:
            groups.append(current_group)
            current_group = []
        current_group.append(word)
        if _is_clause_terminal(word.word):
            groups.append(current_group)
            current_group = []
    if current_group:
        groups.append(current_group)

    cues: list[PhraseCue] = []
    warnings: list[str] = []
    low_confidence_count = 0
    flagged_count = 0
    omitted_count = 0
    for group in groups:
        visible_tokens: list[str] = []
        for word in group:
            is_low_confidence = word.probability is not None and word.probability < cfg.low_confidence_threshold
            if not is_low_confidence:
                visible_tokens.append(word.word)
                continue
            low_confidence_count += 1
            if cfg.on_low_confidence == "flag":
                visible_tokens.append("[?]")
                flagged_count += 1
            else:
                omitted_count += 1
        text = " ".join(visible_tokens).strip()
        if not text:
            if "empty_visible_cue_dropped" not in warnings:
                warnings.append("empty_visible_cue_dropped")
            continue
        cues.append(
            PhraseCue(
                start=group[0].start,
                end=group[-1].end,
                text=text,
                words=tuple(group),
            )
        )

    if flagged_count:
        warnings.insert(0, "low_confidence_tokens_flagged")
    elif omitted_count:
        warnings.insert(0, "low_confidence_tokens_omitted")
    cue_tuple = tuple(cues)
    return CaptionArtifact(
        cues=cue_tuple,
        srt_body=build_srt_body(cue_tuple),
        warnings=tuple(warnings),
        low_confidence_token_count=low_confidence_count,
        omitted_token_count=omitted_count,
    )


def _coerce_word(item: WordTiming | Mapping[str, Any]) -> WordTiming:
    if isinstance(item, WordTiming):
        return item
    if isinstance(item, Mapping):
        return WordTiming.model_validate(item)
    raise TypeError(f"expected WordTiming or mapping, got {type(item).__name__}")


def _is_clause_terminal(text: str) -> bool:
    return text.rstrip().rstrip("\"')]").endswith((".", "!", "?"))


# ---------------------------------------------------------------------------
# Safe caption placement (issue #403)
# ---------------------------------------------------------------------------
# Burn-in is opt-in: ``plan_caption_placement`` only produces reviewable
# placement evidence for the existing burn_in operator to consume later. It
# never invokes ``kinocut.engine_subtitles`` or any other engine op.

_HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"
CaptionStatus = Literal["ready", "blocked"]


class CaptionRegion(ValueObject):
    """Normalized caption rectangle: positive area, contained in the unit frame."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _stays_within_frame(self) -> CaptionRegion:
        """Reject rectangles whose far edges leave the unit frame."""

        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("region must stay within the unit frame")
        return self


class CaptionAppearance(ValueObject):
    """Bounded, immutable visual treatment for a placed caption."""

    font_family: str = Field(min_length=1, max_length=128)
    font_size: int = Field(ge=8, le=200)
    text_color: str = Field(pattern=_HEX_COLOR_PATTERN)
    background_color: str = Field(pattern=_HEX_COLOR_PATTERN)


class CaptionPlacement(ValueObject):
    """Reviewable evidence describing a chosen (or blocked) caption placement."""

    region: CaptionRegion | None = None
    appearance: CaptionAppearance
    status: CaptionStatus
    warning: str | None = None
    burn_in_requested: bool = False

    @model_validator(mode="after")
    def _status_matches_region(self) -> CaptionPlacement:
        """A ready placement must carry a region; a blocked placement must warn."""

        if self.status == "ready":
            if self.region is None:
                raise ValueError("ready placement requires a region")
            if self.warning is not None:
                raise ValueError("ready placement must not carry a warning")
        else:
            if self.region is not None:
                raise ValueError("blocked placement must not select a region")
            if not self.warning:
                raise ValueError("blocked placement must include actionable warning")
        return self


_DEFAULT_APPEARANCE = CaptionAppearance(
    font_family="Inter",
    font_size=42,
    text_color="#FFFFFF",
    background_color="#000000",
)


def plan_caption_placement(
    *,
    candidate_regions: Sequence[CaptionRegion],
    face_regions: Sequence[CaptionRegion] = (),
    product_regions: Sequence[CaptionRegion] = (),
    overlay_regions: Sequence[CaptionRegion] = (),
    appearance: CaptionAppearance | None = None,
    burn_in_requested: bool = False,
) -> CaptionPlacement:
    """Pick the first safe ``CaptionRegion`` or block the placement deterministically.

    A candidate is safe when it has zero positive-area intersection with every
    exclusion region (face, product, platform overlay). Touching edges are
    allowed. When every candidate collides the result has ``status="blocked"``
    with no region and an actionable warning -- never a placement over
    exclusions. Inputs are normalized to deeply immutable tuples so the planner
    is stable across runs and cannot mutate a caller's collection.
    """

    candidates = _freeze_regions(candidate_regions)
    if not candidates:
        raise ValueError("candidate_regions must be a non-empty sequence")
    exclusions = _freeze_regions(face_regions) + _freeze_regions(product_regions) + _freeze_regions(overlay_regions)
    chosen_appearance = appearance or _DEFAULT_APPEARANCE
    for candidate in candidates:
        if not any(_has_positive_overlap(candidate, region) for region in exclusions):
            return CaptionPlacement(
                region=candidate,
                appearance=chosen_appearance,
                status="ready",
                burn_in_requested=burn_in_requested,
            )
    return CaptionPlacement(
        region=None,
        appearance=chosen_appearance,
        status="blocked",
        warning=(f"no_safe_caption_region:candidates={len(candidates)}:exclusions={len(exclusions)}"),
        burn_in_requested=burn_in_requested,
    )


def _freeze_regions(regions: Sequence[CaptionRegion]) -> tuple[CaptionRegion, ...]:
    """Validate and freeze a region sequence, preserving tuple immutability."""

    materialised = tuple(regions)
    for region in materialised:
        if not isinstance(region, CaptionRegion):
            raise TypeError("region inputs must be CaptionRegion instances")
    return materialised


def _has_positive_overlap(candidate: CaptionRegion, region: CaptionRegion) -> bool:
    """Return ``True`` iff two rectangles share strictly-positive interior area."""

    left = max(candidate.x, region.x)
    bottom = max(candidate.y, region.y)
    right = min(candidate.x + candidate.width, region.x + region.width)
    top = min(candidate.y + candidate.height, region.y + region.height)
    return right > left and top > bottom


__all__ = [
    "CaptionAppearance",
    "CaptionArtifact",
    "CaptionConfig",
    "CaptionPlacement",
    "CaptionRegion",
    "CaptionStatus",
    "LowConfidencePolicy",
    "PhraseCue",
    "WordTiming",
    "build_caption_artifact",
    "build_srt_body",
    "plan_caption_placement",
]
