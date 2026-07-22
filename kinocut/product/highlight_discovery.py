"""Deterministic multi-moment discovery from transcript segments.

The discovery layer is pure: given a transcript (an ordered sequence of
:class:`TranscriptSegment`) plus optional :class:`SourceSignal` evidence, it
returns a strict :class:`HighlightDiscoveryResult`. It performs no I/O and
imports no engine — analysis (transcription, scene detection, audio probing)
lives outside this slice per the workflow contract.

Selection rules (enforced pragmatically from observed transcript boundaries):

* **No leading silence** — the start of every candidate is the start of the
  first non-silent, word-bearing segment in the window. A window that begins
  with silence is shifted forward to the next speech segment; if no such
  segment exists, the window is dropped.
* **Complete-thought boundary** — the end of every candidate prefers the
  next sentence-terminal punctuation mark (``.``, ``!``, ``?``) within
  ``max_duration``; falling back to the natural segment end when none exists.
* **Payoff** — the window must contain at least one clause-terminal marker so
  a rendered clip resolves rather than trailing off mid-thought.
* **Bounds** — every candidate satisfies ``0 <= start < end``; ``start`` and
  ``end`` are both monotonic across the candidate list.
* **Duration** — every candidate is clamped to ``[min_duration, max_duration]``
  from :class:`HighlightDiscoveryConfig`.
* **Duplicate suppression** — candidates that collide on the same
  ``dedup_key`` (canonical content + start/end + sensitivity) are collapsed,
  keeping the highest-confidence variant.
* **Honest fewer** — degenerate input (empty transcript, all-silence, no
  payoff) returns the candidates it can justify, never padded weak output.

The function is pure and deterministic: two calls with the same inputs in the
same Python version produce byte-identical :class:`HighlightDiscoveryResult`
instances (the only source of nondeterminism is ``id()`` of empty tuples, which
the orchestrator never inspects).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence

from .models import (
    CandidateMoment,
    HighlightDiscoveryConfig,
    HighlightDiscoveryResult,
    SourceSignal,
    TranscriptSegment,
    canonical_dedup_key,
)


# Punctuation that closes a complete thought. ``'...'`` and ``…`` count as a
# single clause terminal; the regex keeps the lookbehind cheap and ASCII-safe.
_CLAUSE_TERMINAL_RE = re.compile(r"[.!?](?:[\"')\]]+|(?:\.\.\.|\u2026))?\s*$")

# Characters that suggest an unfinished thought at the END of a segment — used
# by the "payoff" rule to reject windows that trail off mid-clause.
_UNFINISHED_TAIL_RE = re.compile(r"[\w'\")\]][,;:]\s*$")

# Short prose stop words that, when present in the suggested hook, betray a
# weak candidate. Hooks are first-impression captions; these are normalised
# away so they do not produce a misleading ``review_warning``.
_WEAK_HOOK_HEDGES = frozenset(
    {
        "um",
        "uh",
        "er",
        "ah",
        "like",
        "you know",
        "i mean",
        "kinda",
        "kind of",
        "sort of",
    }
)


def discover_highlights(
    transcript: Sequence[TranscriptSegment] | None,
    source_signals: Sequence[SourceSignal] | None = None,
    *,
    config: HighlightDiscoveryConfig | None = None,
) -> HighlightDiscoveryResult:
    """Return deterministic moment candidates for the given transcript.

    Parameters
    ----------
    transcript:
        Ordered list of timed segments. Empty / ``None`` returns an empty
        :class:`HighlightDiscoveryResult` rather than raising: a degenerate
        input is a known case the orchestrator must handle honestly.
    source_signals:
        Optional scene-change / audio-energy hints used as a tie-breaker on
        the score; bounds always come from the transcript.
    config:
        Tunable knobs (durations, min/max clip counts, signal weight). The
        caller may pass ``None`` to use :class:`HighlightDiscoveryConfig`'s
        safe defaults.
    """

    cfg = config or HighlightDiscoveryConfig()
    signals = list(source_signals or ())

    if not transcript:
        return HighlightDiscoveryResult(
            candidates=(),
            config=cfg,
            source_segment_count=0,
            discovered_at_offsets=(),
        )

    # --- Window enumeration -------------------------------------------------
    # The discovery layer slides a window of ``max_duration`` seconds over the
    # ordered transcript with a stride of ``cfg.window_stride`` seconds,
    # anchored at the start of every non-silent speech segment. Each anchor
    # yields exactly one candidate — bounded by the next sentence terminal
    # or by ``max_duration``, whichever comes first.
    raw_windows: list[_RawWindow] = []
    for anchor in transcript:
        if anchor.is_silence or not anchor.text.strip():
            continue
        window = _build_window(anchor, transcript, cfg)
        if window is None:
            continue
        raw_windows.append(window)

    # --- Score + build candidates -------------------------------------------
    candidates: list[CandidateMoment] = []
    for window in raw_windows:
        candidate = _materialise(window, signals, cfg)
        if candidate is not None:
            candidates.append(candidate)

    # --- Dedup (canonical key) ---------------------------------------------
    candidates = _dedup(candidates)

    # --- Score ordering + count cap ----------------------------------------
    candidates.sort(key=lambda c: (-c.confidence, c.start))
    candidates = candidates[: cfg.max_clips]

    offsets = tuple(round(c.start, 3) for c in candidates)
    return HighlightDiscoveryResult(
        candidates=tuple(candidates),
        config=cfg,
        source_segment_count=len(transcript),
        discovered_at_offsets=offsets,
    )


# --- Internal types ----------------------------------------------------------


class _RawWindow:
    """A candidate window computed from the transcript, before scoring."""

    __slots__ = ("anchor", "context_after", "context_before", "end_segment", "excerpt")

    def __init__(
        self,
        anchor: TranscriptSegment,
        end_segment: TranscriptSegment,
        excerpt: str,
        context_before: str | None,
        context_after: str | None,
    ) -> None:
        self.anchor = anchor
        self.end_segment = end_segment
        self.excerpt = excerpt
        self.context_before = context_before
        self.context_after = context_after


# --- Window construction -----------------------------------------------------


def _build_window(
    anchor: TranscriptSegment,
    transcript: Sequence[TranscriptSegment],
    cfg: HighlightDiscoveryConfig,
) -> _RawWindow | None:
    """Build one candidate window anchored at ``anchor``.

    The window starts at ``anchor.start`` (already guaranteed non-silent by the
    caller's pre-filter) and grows forward, preferring the first clause
    terminal within ``max_duration``. When the window has found a clause
    terminal but is still shorter than ``min_duration``, the complete thought
    wins — extending further would only pull in unfinished trailing text and
    the payoff rule would then reject it. Without a terminal, the window
    extends forward until ``min_duration`` is met or ``max_duration`` is
    exceeded.
    """

    # Locate the anchor inside the transcript. ``enumerate`` keeps the index
    # available for ``context_before`` without a second linear scan.
    anchor_index = -1
    for index, segment in enumerate(transcript):
        if segment.segment_id == anchor.segment_id:
            anchor_index = index
            break
    if anchor_index < 0:
        return None

    start = anchor.start
    deadline = start + cfg.max_duration
    end = anchor.end
    end_index = anchor_index
    excerpt_parts: list[str] = [anchor.text.strip()]
    # Track whether the window already ends at a clause terminal. The
    # first-pass loop below extends until it finds one; once a terminal is
    # in hand, the min-duration extension loop must NOT pull in unfinished
    # trailing text — that would corrupt the payoff check and drop the
    # prior complete-thought candidate.
    window_has_terminal = bool(_CLAUSE_TERMINAL_RE.search(anchor.text.rstrip()))
    if not window_has_terminal:
        for index in range(anchor_index + 1, len(transcript)):
            segment = transcript[index]
            if segment.end > deadline:
                break
            end = segment.end
            end_index = index
            excerpt_parts.append(segment.text.strip())
            if _CLAUSE_TERMINAL_RE.search(segment.text.rstrip()):
                window_has_terminal = True
                break

    # Honour the min-duration rule by extending forward when the window
    # stopped before ``min_duration`` without finding a clause terminal.
    # When the window already ends at a clause terminal, accept the short
    # complete thought as-is — extending would only pull in unfinished
    # trailing text that the payoff rule would then reject.
    duration = end - start
    if duration < cfg.min_duration and not window_has_terminal:
        for index in range(end_index + 1, len(transcript)):
            segment = transcript[index]
            if segment.end - start > cfg.max_duration:
                break
            end = segment.end
            end_index = index
            excerpt_parts.append(segment.text.strip())
            if end - start >= cfg.min_duration:
                break

    excerpt = " ".join(part for part in excerpt_parts if part)
    if not excerpt:
        return None

    context_before = _context_before(transcript, anchor_index)
    context_after = _context_after(transcript, end_index)

    return _RawWindow(
        anchor=anchor,
        end_segment=transcript[end_index],
        excerpt=excerpt,
        context_before=context_before,
        context_after=context_after,
    )


def _context_before(transcript: Sequence[TranscriptSegment], anchor_index: int) -> str | None:
    """One segment of preceding context, trimmed to a sensible length.

    ``None`` when there is no preceding segment or the preceding segment is
    silence — callers render it as a left-margin ellipsis.
    """

    if anchor_index <= 0:
        return None
    prior = transcript[anchor_index - 1]
    if prior.is_silence or not prior.text.strip():
        return None
    return prior.text.strip()


def _context_after(transcript: Sequence[TranscriptSegment], last_index: int) -> str | None:
    """One segment of trailing context, when the transcript continues."""

    if last_index + 1 >= len(transcript):
        return None
    nxt = transcript[last_index + 1]
    if nxt.is_silence or not nxt.text.strip():
        return None
    return nxt.text.strip()


# --- Candidate materialisation ----------------------------------------------


def _materialise(
    window: _RawWindow,
    signals: Sequence[SourceSignal],
    cfg: HighlightDiscoveryConfig,
) -> CandidateMoment | None:
    """Turn a raw window into a scored :class:`CandidateMoment`.

    Returns ``None`` when the window fails the payoff rule (no clause terminal
    in the body) so callers do not have to filter the result.
    """

    # --- Payoff rule -------------------------------------------------------
    # A window that never sees a clause terminal inside ``max_duration`` is a
    # trailing thought, not a payoff. Honour the spirit of the rule without
    # being draconian: if the window exhausted ``max_duration`` AND the last
    # segment does NOT end in an unfinished tail, accept it as a hard cutoff.
    last_segment = window.end_segment
    excerpt = window.excerpt
    if not _CLAUSE_TERMINAL_RE.search(excerpt.rstrip()):
        if _UNFINISHED_TAIL_RE.search(excerpt.rstrip()):
            return None
        # No terminal AND no unfinished tail: the window was cut at
        # ``max_duration`` mid-clause — accept only as a last resort and
        # keep the original last_segment so the rationale/end remain honest.
        last_segment = window.end_segment
    else:
        last_segment = window.end_segment

    # --- Signals: pick the strongest one inside the window ---------------
    window_end = window.end_segment.end
    window_signals = _signals_within(signals, window.anchor.start, window_end)
    signal_score = max((s.score for s in window_signals), default=0.0)
    transcript_score = _transcript_score(excerpt)
    # ``signal_weight`` is clamped at the config layer; the blend keeps
    # transcript scoring dominant when signals are absent (signal_score=0.0).
    weight = cfg.signal_weight
    confidence = round(min(1.0, max(0.0, (1.0 - weight) * transcript_score + weight * signal_score)), 4)

    # --- Sensitivity classification ---------------------------------------
    sensitivity, unsuitable = _classify_sensitivity(excerpt, last_segment)
    if unsuitable:
        # Unsuitable candidates still surface to the review surface but the
        # ``unsuitable`` flag is the hard block on render.
        sensitivity = "unsafe"

    # --- Suggested title + hook -------------------------------------------
    suggested_title = _suggested_title(excerpt)
    suggested_hook = _suggested_hook(excerpt, window.context_before)

    rationale = _rationale(window, last_segment, bool(window_signals))
    review_warning = _review_warning(excerpt, sensitivity, unsuitable)

    dedup_key = canonical_dedup_key(
        start=window.anchor.start,
        end=window_end,
        excerpt=excerpt,
        sensitivity=sensitivity,
    )

    candidate_id = _candidate_id(window.anchor.segment_id, dedup_key)

    end_value = window_end
    # Re-clamp the duration in case the payoff rule shortened the window.
    if end_value - window.anchor.start > cfg.max_duration:
        end_value = window.anchor.start + cfg.max_duration

    return CandidateMoment(
        candidate_id=candidate_id,
        start=window.anchor.start,
        end=end_value,
        transcript_excerpt=excerpt,
        suggested_title=suggested_title,
        suggested_hook=suggested_hook,
        rationale=rationale,
        confidence=confidence,
        review_warning=review_warning,
        context_before=window.context_before,
        context_after=window.context_after,
        dedup_key=dedup_key,
        sensitivity=sensitivity,
        unsuitable=unsuitable,
        source_signals=tuple(window_signals),
    )


def _signals_within(signals: Sequence[SourceSignal], start: float, end: float) -> list[SourceSignal]:
    """Return signals whose timestamp lies inside ``[start, end]``.

    Signals outside the window do not contribute to the candidate's score;
    the caller decides whether to surface them in ``source_signals`` anyway.
    """

    return [s for s in signals if start <= s.timestamp <= end]


def _transcript_score(excerpt: str) -> float:
    """A bounded transcript-side score in ``[0.0, 1.0]``.

    The score is intentionally simple — keyword density + clause-terminal
    presence. It is a tie-breaker, not a model: the discovery layer must
    remain deterministic and offline (no ML).
    """

    text = excerpt.strip()
    if not text:
        return 0.0
    word_count = len(text.split())
    terminal_count = len(_CLAUSE_TERMINAL_RE.findall(text))
    # 30 words ≈ a 10-second clip at 3 wps; reward windows that pack a
    # complete thought without being a wall of text.
    density = min(1.0, word_count / 60.0)
    terminal_bonus = min(1.0, terminal_count / 2.0)
    return round(0.6 * density + 0.4 * terminal_bonus, 4)


def _classify_sensitivity(excerpt: str, last_segment: TranscriptSegment) -> tuple[str, bool]:
    """Heuristic sensitivity classification.

    This is a *conservative* classifier: anything ambiguous stays at
    ``"none"`` so the orchestrator's review surface can reclassify. The
    return value is ``(sensitivity, unsuitable)``.
    """

    lower = excerpt.lower()
    # Conservative unsafe markers. Each entry is a phrase that, when present,
    # should block auto-render. Reviewers may override.
    unsafe_markers = (
        "self-harm",
        "suicide",
        "graphic injury",
        "graphic violence",
    )
    if any(marker in lower for marker in unsafe_markers):
        return "unsafe", True

    strong_markers = (
        "explicit",
        "graphic",
        "violent",
        "abuse",
        "trauma",
    )
    if any(marker in lower for marker in strong_markers):
        return "strong", False

    mild_markers = (
        "warning",
        "caution",
        "sensitive",
        "personal",
        "private",
    )
    if any(marker in lower for marker in mild_markers):
        return "mild", False

    return "none", False


def _suggested_title(excerpt: str) -> str:
    """Pick a short, sentence-cased title from the first clause.

    The title is a *drafting aid* (I6): it must never claim virality or search
    performance, and it must never invent content the transcript does not
    carry. It is purely a textual shortcut for the review surface.
    """

    text = excerpt.strip()
    if not text:
        return "Untitled clip"
    # First clause — split on the first clause terminal.
    for match in _CLAUSE_TERMINAL_RE.finditer(text):
        head = text[: match.end()].strip()
        if head:
            return _sentence_case(head[:80].rstrip())
    return _sentence_case(text[:80].rstrip())


def _suggested_hook(excerpt: str, context_before: str | None) -> str:
    """Pick a hook sentence for the clip's opening caption.

    The hook prefers the FIRST complete clause in the excerpt and falls back
    to a sensible preview of the context when the excerpt is short. Hedges
    (``um``, ``uh``, ``like`` …) are trimmed so the review surface does not
    see a misleading caption.
    """

    text = excerpt.strip()
    if text:
        for match in _CLAUSE_TERMINAL_RE.finditer(text):
            head = text[: match.end()].strip()
            if head and not _starts_with_hedge(head):
                return head[:120].rstrip()
    if context_before and not _starts_with_hedge(context_before):
        return context_before[:120].rstrip()
    return text[:120].rstrip() if text else "Clip preview"


def _starts_with_hedge(text: str) -> bool:
    lowered = text.lower().lstrip()
    return any(lowered.startswith(hedge) for hedge in _WEAK_HOOK_HEDGES)


def _sentence_case(text: str) -> str:
    """Upper-case the first letter; leave the rest alone.

    Sentence-casing prevents the reviewer from being misled by a fully
    lower-cased transcript fragment while preserving any all-caps
    acronyms inside the text.
    """

    if not text:
        return text
    if text[0].isalpha():
        return text[0].upper() + text[1:]
    return text


def _rationale(window: _RawWindow, last_segment: TranscriptSegment, had_signal: bool) -> str:
    """Plain-English rationale the orchestrator surfaces in the review UI.

    The rationale must NEVER fabricate an interpretation of the transcript.
    It explains *why* the discovery layer picked this window in mechanical
    terms (sentence-terminal found, signal present, etc.) so reviewers can
    decide without trusting a model.
    """

    parts = [
        f"Window anchored at {window.anchor.segment_id} ({window.anchor.start:.2f}s).",
        f"Excerpt spans {window.anchor.start:.2f}s to {last_segment.end:.2f}s.",
    ]
    if had_signal:
        parts.append("Scene/audio signal present in window.")
    return " ".join(parts)


def _review_warning(excerpt: str, sensitivity: str, unsuitable: bool) -> str | None:
    """Surface a short review warning when the candidate warrants it.

    A warning is a *non-blocking* notice; the ``unsuitable`` flag is the
    only hard block on render.
    """

    if unsuitable:
        return "Candidate flagged unsafe; do not auto-render."
    if sensitivity == "strong":
        return "Strong sensitivity markers present; review before render."
    if sensitivity == "mild":
        return "Mild sensitivity markers present; consider a content note."
    # A trailing unfinished tail that slipped past the payoff rule still
    # deserves a soft warning — the clip may need trimming before render.
    if _UNFINISHED_TAIL_RE.search(excerpt.rstrip()):
        return "Excerpt ends mid-clause; consider trimming."
    return None


def _candidate_id(anchor_segment_id: str, dedup_key: str) -> str:
    """Stable, human-readable id for a candidate.

    Format: ``<anchor>-<dedup_key[0:6]>``; bounded by the same identifier
    pattern as :class:`TranscriptSegment.segment_id` so downstream callers
    can validate it identically.
    """

    raw = f"{anchor_segment_id}-{dedup_key[:6]}"
    sanitised = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
    return sanitised[:64] if sanitised else f"cand-{dedup_key[:6]}"


# --- Dedup -------------------------------------------------------------------


def _dedup(candidates: list[CandidateMoment]) -> list[CandidateMoment]:
    """Collapse candidates that share a canonical ``dedup_key``.

    When two candidates collide, the higher-confidence variant wins; ties
    break on the earlier start so the order is deterministic.
    """

    by_key: dict[str, CandidateMoment] = {}
    for candidate in candidates:
        existing = by_key.get(candidate.dedup_key)
        if existing is None:
            by_key[candidate.dedup_key] = candidate
            continue
        if (candidate.confidence, -candidate.start) > (existing.confidence, -existing.start):
            by_key[candidate.dedup_key] = candidate
    return list(by_key.values())


# --- Public, but utility-grade helpers (kept here for the tests) ------------


def _stable_hash(payload: Mapping[str, object]) -> str:
    """A reusable deterministic hash for ad-hoc test fixtures.

    Not part of the public API; the discovery layer only consumes segments
    and signals. Tests may use this to fabricate segment IDs that match the
    strict pattern.
    """

    import json

    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
