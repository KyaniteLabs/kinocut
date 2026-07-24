"""Deterministic, evidence-grounded highlight candidate discovery.

Discovery contract:

* **Monotonic input** — segments are accepted only when their ``start`` is
  non-decreasing.  Strictly-decreasing inputs raise ``ValueError`` so callers
  learn about overlap upstream rather than silently receiving reordered windows.
* **In-window signal preservation** — ``SourceSignal`` entries whose timestamp
  falls inside ``[anchor.start, end_segment.end]`` (inclusive on both ends) are
  preserved on the candidate, sorted deterministically, and out-of-window
  signals are excluded.  In-window evidence may truthfully affect confidence
  and therefore candidate ordering.
* **Bounded complete-thought windows** — every candidate window obeys
  ``min_duration <= end - start <= max_duration`` and ends at a terminal mark
  (``.``, ``!``, ``?``) so the rendered clip resolves rather than trailing off.
* **Distinct, non-degenerate title and hook** — the title is the first
  sentence of the excerpt, the hook is the first *two* sentences, and neither
  is allowed to degenerate to a known abbreviation ("Dr."), a single capital
  initial ("U. S. A."), or a decimal point ("3.14").

Transcript evidence remains authoritative; enrichment adds bounded signal
weighting, sensitivity escalation, context, rationale, and review warnings.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import pairwise

from .models import (
    CandidateMoment,
    HighlightDiscoveryConfig,
    HighlightDiscoveryResult,
    SourceSignal,
    TranscriptSegment,
    canonical_dedup_key,
)

# A period only counts as a sentence end when it is *not* a known abbreviation
# (single-letter initials, honorifics, Latin/English abbreviations) or a decimal
# point between two digits.  Without this guard "Dr. Smith explains." or
# "3.14 percent improved." would degenerate the title to "Dr." / "3.".
_ABBREVIATION_RE = re.compile(
    r"\b(?:[A-Za-z]\.){1,4}|"
    r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|No|Inc|Ltd|Co|Corp|"
    r"e\.g|i\.e|cf|al|approx|dept|est|govt)\.",
    re.IGNORECASE,
)
_DECIMAL_RE = re.compile(r"\d\.\d")
# Boundary-only terminal: a punctuation mark followed by optional quotes /
# brackets, then end-of-string.  Used to decide whether a single segment closes
# a complete thought; the search is restricted to the *end* of the segment
# because an internal "Dr." or "3.14" is never a complete-thought boundary.
_BOUNDARY_TERMINAL_RE = re.compile(r"[.!?](?:[\"')\]]+)?\s*$")
# In-text terminal: a punctuation mark followed by whitespace (or another
# sentence start) so we can scan through a multi-sentence excerpt while still
# ignoring decorative periods.
_INNER_TERMINAL_RE = re.compile(r"[.!?](?:[\"')\]]+)?(?=\s|$)")
_CHAR_LIMIT_TITLE = 80
_CHAR_LIMIT_HOOK = 160
_UNSAFE_RE = re.compile(r"\b(?:suicide|self-harm|kill|murder|overdose)\b", re.IGNORECASE)
_UNSAFE_WARNING = "Unsafe or sensitive transcript terms require editorial review."


def discover_highlights(
    transcript: Sequence[TranscriptSegment],
    *,
    signals: Sequence[SourceSignal] = (),
    config: HighlightDiscoveryConfig | None = None,
) -> HighlightDiscoveryResult:
    """Discover bounded, complete-thought candidates with editorial evidence.

    Candidate confidence is transcript-only at the base; in-window signals are
    blended in via ``HighlightDiscoveryConfig.signal_weight`` so the same
    transcript re-discovered with a richer signal set produces a strictly
    ordered set of candidates.  Sensitivity escalation, context, rationale,
    and review warnings are attached as evidence without inventing copy.

    Raises:
        ValueError: when any adjacent pair of segments has ``current.start <
            previous.start`` (strictly non-monotonic input).  Equal ``start``
            offsets are allowed because they model ASR boundary artefacts
            where two segments share a boundary timestamp.
    """
    cfg = config or HighlightDiscoveryConfig()
    segments = tuple(transcript)
    source_signals = tuple(signals)
    if any(current.start < previous.start for previous, current in pairwise(segments)):
        raise ValueError("transcript segments must be monotonic by start offset")

    candidates: list[CandidateMoment] = []
    for anchor_index, anchor in enumerate(segments):
        if anchor.is_silence or not anchor.text.strip():
            continue
        candidate = _candidate_for_anchor(segments, anchor_index, source_signals, cfg)
        if candidate is not None:
            candidates.append(candidate)

    by_key: dict[str, CandidateMoment] = {}
    for candidate in candidates:
        existing = by_key.get(candidate.dedup_key)
        if existing is None or _sort_key(candidate) < _sort_key(existing):
            by_key[candidate.dedup_key] = candidate
    ordered = sorted(by_key.values(), key=_sort_key)[: cfg.max_clips]
    return HighlightDiscoveryResult(
        candidates=tuple(ordered),
        config=cfg,
        source_segment_count=len(segments),
        discovered_at_offsets=tuple(round(candidate.start, 3) for candidate in ordered),
    )


def _candidate_for_anchor(
    segments: tuple[TranscriptSegment, ...],
    anchor_index: int,
    signals: tuple[SourceSignal, ...],
    config: HighlightDiscoveryConfig,
) -> CandidateMoment | None:
    anchor = segments[anchor_index]
    parts: list[str] = []
    end_index: int | None = None

    for index in range(anchor_index, len(segments)):
        segment = segments[index]
        if segment.end - anchor.start > config.max_duration:
            break
        if segment.is_silence or not segment.text.strip():
            continue
        parts.append(segment.text.strip())
        if segment.end - anchor.start >= config.min_duration and _is_complete(segment.text):
            end_index = index
            break

    if end_index is None:
        return None
    end_segment = segments[end_index]
    excerpt = " ".join(parts)
    sensitivity = "unsafe" if _UNSAFE_RE.search(excerpt) else "none"
    key = canonical_dedup_key(
        start=anchor.start,
        end=end_segment.end,
        excerpt=excerpt,
        sensitivity=sensitivity,
    )
    title = _excerpt_title(excerpt)
    hook = _excerpt_hook(excerpt)
    # Window inclusion is inclusive on both ends so signals that land exactly
    # on a window boundary (e.g. a scene change at the closing edit) are
    # preserved as evidence rather than dropped.
    window_signals = tuple(
        sorted(
            (signal for signal in signals if anchor.start <= signal.timestamp <= end_segment.end),
            key=lambda signal: (
                signal.timestamp,
                signal.kind,
                -signal.score,
                signal.label or "",
            ),
        )
    )
    confidence = _confidence(excerpt, window_signals, config.signal_weight)
    signal_kinds = ", ".join(sorted({signal.kind for signal in window_signals}))
    rationale = "Complete transcript thought"
    if signal_kinds:
        rationale += f" with in-window {signal_kinds} evidence"
    rationale += "."
    return CandidateMoment(
        candidate_id=_candidate_id(anchor.segment_id, key),
        start=anchor.start,
        end=end_segment.end,
        transcript_excerpt=excerpt,
        suggested_title=title,
        suggested_hook=hook,
        rationale=rationale,
        confidence=confidence,
        review_warning=_UNSAFE_WARNING if sensitivity == "unsafe" else None,
        context_before=_adjacent_context(segments, anchor_index - 1),
        context_after=_adjacent_context(segments, end_index + 1),
        dedup_key=key,
        sensitivity=sensitivity,
        unsuitable=sensitivity == "unsafe",
        source_signals=window_signals,
    )


def _is_complete(text: str) -> bool:
    """Return True when *text* ends at a real sentence terminal.

    The boundary regex anchors to end-of-string so an internal "Dr." or "3.14"
    cannot accidentally close a window.  The full excerpt is re-scanned by
    :func:`_excerpt_title` / :func:`_excerpt_hook` with the stronger
    abbreviation-aware logic.
    """
    return bool(_BOUNDARY_TERMINAL_RE.search(text.rstrip()))


def _is_decorative_period(text: str, index: int) -> bool:
    """Return True when the period at *index* is part of an abbreviation or decimal."""
    return any(
        match.start() <= index < match.end()
        for pattern in (_ABBREVIATION_RE, _DECIMAL_RE)
        for match in pattern.finditer(text)
    )


def _transcript_score(excerpt: str) -> float:
    words = len(excerpt.split())
    terminals = sum(1 for token in excerpt.split() if _is_complete(token))
    density = min(1.0, words / 60.0)
    completeness = min(1.0, terminals / 2.0)
    return round(min(1.0, 0.6 * density + 0.4 * completeness), 4)


def _confidence(excerpt: str, signals: tuple[SourceSignal, ...], weight: float) -> float:
    transcript_score = _transcript_score(excerpt)
    if not signals:
        return transcript_score
    signal_score = max(signal.score for signal in signals)
    return round((1.0 - weight) * transcript_score + weight * signal_score, 4)


def _adjacent_context(segments: tuple[TranscriptSegment, ...], index: int) -> str | None:
    if 0 <= index < len(segments):
        return segments[index].text.strip() or None
    return None


def _excerpt_title(excerpt: str) -> str:
    """Return the first *real* sentence of *excerpt*, truncated to fit a title.

    Sentence boundaries are scanned left-to-right while skipping periods that
    belong to known abbreviations or decimal numbers.  When the chosen lead
    still exceeds the title character cap the result falls back to the longest
    word-boundary-respecting prefix so a degenerate substring like "Dr" never
    ships as a title.
    """
    first = _first_n_sentences(excerpt, 1)
    if not first:
        return _truncate_to_word_boundary(excerpt.strip(), _CHAR_LIMIT_TITLE)
    return _fit_to_char_limit(first[0], _CHAR_LIMIT_TITLE)


def _excerpt_hook(excerpt: str) -> str:
    """Return the first *two* real sentences of *excerpt*, truncated to fit a hook.

    The hook is required to be visibly different from the title; when the
    excerpt contains only one sentence the hook extends up to the hook cap so
    it carries more context than the title alone.
    """
    sentences = _first_n_sentences(excerpt, 2)
    if len(sentences) >= 2:
        return _fit_to_char_limit(" ".join(sentences), _CHAR_LIMIT_HOOK)
    if sentences:
        return _fit_to_char_limit(sentences[0], _CHAR_LIMIT_HOOK)
    return _truncate_to_word_boundary(excerpt.strip(), _CHAR_LIMIT_HOOK)


def _first_n_sentences(excerpt: str, n: int) -> list[str]:
    sentences: list[str] = []
    cursor = 0
    for match in _INNER_TERMINAL_RE.finditer(excerpt):
        if _is_decorative_period(excerpt, match.start()):
            continue
        sentence = excerpt[cursor : match.start() + 1].strip()
        if not sentence:
            continue
        sentences.append(sentence)
        cursor = match.end()
        if len(sentences) >= n:
            break
    return sentences


def _fit_to_char_limit(sentence: str, char_limit: int) -> str:
    if len(sentence) <= char_limit:
        return sentence
    return _truncate_to_word_boundary(sentence, char_limit)


def _truncate_to_word_boundary(text: str, char_limit: int) -> str:
    if len(text) <= char_limit:
        return text
    head = text[:char_limit].rstrip()
    if " " not in head:
        return head
    return head.rsplit(" ", 1)[0].rstrip()


def _candidate_id(segment_id: str, dedup_key: str) -> str:
    prefix = re.sub(r"[^A-Za-z0-9._-]", "_", segment_id)
    return f"{prefix[:57]}-{dedup_key[:6]}"


def _sort_key(candidate: CandidateMoment) -> tuple[float, float, float, str]:
    return (-candidate.confidence, candidate.start, candidate.end, candidate.candidate_id)
