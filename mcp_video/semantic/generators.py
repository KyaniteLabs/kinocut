"""Ordinary-person edit behaviors compiled into the shared EDL contract."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Literal

from mcp_video.errors import ValidationError as MCPValidationError

from .edl import EditAction, EditDecisionList, EditOperation, create_edl, make_edit
from .models import SemanticTimeline, SourceSpan, WordSpan


def _delete(
    span: SourceSpan,
    rationale: str,
    *,
    start: float | None = None,
    end: float | None = None,
) -> EditAction:
    return make_edit(
        operation=EditOperation.DELETE,
        target_span=span,
        source_start_seconds=start,
        source_end_seconds=end,
        rationale=rationale,
    )


def generate_silence_edl(
    timeline: SemanticTimeline,
    *,
    max_silence_seconds: float = 0.5,
    min_confidence: float = 0.8,
) -> EditDecisionList:
    """Shorten only confidently identified silence, preserving equal edge context."""

    if max_silence_seconds < 0:
        raise MCPValidationError("max_silence_seconds", "must be non-negative")
    edits: list[EditAction] = []
    for silence in timeline.silences:
        duration = silence.source_end_seconds - silence.source_start_seconds
        if silence.confidence < min_confidence or silence.uncertainty or duration <= max_silence_seconds:
            continue
        edge = max_silence_seconds / 2
        edits.append(
            _delete(
                silence,
                "shorten source-detected silence",
                start=round(silence.source_start_seconds + edge, 9),
                end=round(silence.source_end_seconds - edge, 9),
            )
        )
    return create_edl(timeline, edits=edits)


def _confident_observed(word: WordSpan, min_confidence: float) -> bool:
    return word.confidence >= min_confidence and word.text_status == "observed" and not word.uncertainty


def generate_filler_edl(timeline: SemanticTimeline, *, min_confidence: float = 0.85) -> EditDecisionList:
    edits = tuple(
        _delete(word, "remove source-labeled filler")
        for word in timeline.words
        if word.disfluency == "filler" and _confident_observed(word, min_confidence)
    )
    return create_edl(timeline, edits=edits)


def generate_false_start_edl(timeline: SemanticTimeline, *, min_confidence: float = 0.85) -> EditDecisionList:
    edits = tuple(
        _delete(word, "remove source-labeled false start")
        for word in timeline.words
        if word.disfluency == "false_start" and _confident_observed(word, min_confidence)
    )
    return create_edl(timeline, edits=edits)


def _retake_groups(words: Sequence[WordSpan]) -> dict[str, list[WordSpan]]:
    groups: dict[str, list[WordSpan]] = defaultdict(list)
    for word in words:
        if word.retake_group_id is not None:
            groups[word.retake_group_id].append(word)
    return groups


def _selected_take(words: Sequence[WordSpan], min_confidence: float) -> str | None:
    if not all(_confident_observed(word, min_confidence) for word in words):
        return None
    selected = {word.take_id for word in words if word.selected_take}
    if len(selected) != 1:
        return None
    selected_take = next(iter(selected))
    if any(word.take_id == selected_take and not word.selected_take for word in words):
        return None
    return selected_take


def generate_retake_edl(timeline: SemanticTimeline, *, min_confidence: float = 0.85) -> EditDecisionList:
    """Delete only takes carrying one explicit, consistent source-backed selection."""

    edits: list[EditAction] = []
    for group_id, words in sorted(_retake_groups(timeline.words).items()):
        selected_take = _selected_take(words, min_confidence)
        if selected_take is None:
            continue
        edits.extend(
            _delete(word, f"remove unselected retake in group {group_id}")
            for word in words
            if word.take_id != selected_take
        )
    return create_edl(timeline, edits=edits)


def generate_pacing_edl(
    timeline: SemanticTimeline,
    *,
    max_silence_seconds: float = 0.5,
    remove_fillers: bool = False,
    min_confidence: float = 0.85,
) -> EditDecisionList:
    silence = generate_silence_edl(
        timeline,
        max_silence_seconds=max_silence_seconds,
        min_confidence=min_confidence,
    )
    fillers = generate_filler_edl(timeline, min_confidence=min_confidence) if remove_fillers else None
    edits = (*silence.edits, *(fillers.edits if fillers else ()))
    return create_edl(timeline, edits=tuple(sorted(edits, key=lambda edit: (edit.source_start_seconds, edit.edit_id))))


def _covering_span(timeline: SemanticTimeline, start: float, end: float) -> SourceSpan:
    for span in (*timeline.shots, *timeline.scenes):
        if span.source_start_seconds <= start < end <= span.source_end_seconds:
            return span
    raise MCPValidationError("trim", "trim ranges require a shot or scene span that fully covers source time")


def generate_trim_edl(
    timeline: SemanticTimeline,
    *,
    keep_start_seconds: float,
    keep_end_seconds: float,
) -> EditDecisionList:
    duration = timeline.source.duration_seconds
    if not 0 <= keep_start_seconds < keep_end_seconds <= duration:
        raise MCPValidationError("trim", "keep range must be positive and within source duration")
    edits: list[EditAction] = []
    if keep_start_seconds > 0:
        edits.append(
            _delete(
                _covering_span(timeline, 0.0, keep_start_seconds), "trim source head", start=0.0, end=keep_start_seconds
            )
        )
    if keep_end_seconds < duration:
        edits.append(
            _delete(
                _covering_span(timeline, keep_end_seconds, duration),
                "trim source tail",
                start=keep_end_seconds,
                end=duration,
            )
        )
    return create_edl(timeline, edits=edits)


def generate_reorder_edl(
    timeline: SemanticTimeline,
    *,
    ordered_span_ids: Sequence[str],
) -> EditDecisionList:
    if len(ordered_span_ids) != len(set(ordered_span_ids)):
        raise MCPValidationError("ordered_span_ids", "reorder span ids must be unique")
    spans: list[SourceSpan] = []
    for span_id in ordered_span_ids:
        span = timeline.span_by_id(span_id)
        if span is None:
            raise MCPValidationError("ordered_span_ids", "every reorder id must reference an exact semantic span")
        spans.append(span)
    ordered_by_time = sorted(spans, key=lambda span: span.source_start_seconds)
    if any(left.source_end_seconds > right.source_start_seconds for left, right in pairwise(ordered_by_time)):
        raise MCPValidationError("ordered_span_ids", "reordered source spans must not overlap")
    edits = tuple(
        make_edit(
            operation=EditOperation.REORDER,
            target_span=span,
            destination_index=index,
            rationale="apply explicit transcript timeline order",
        )
        for index, span in enumerate(spans)
    )
    return create_edl(timeline, edits=edits)


Behavior = Literal["silence", "filler", "false_start", "retake", "pacing", "trim", "reorder"]


def generate_ordinary_cleanup_edits(
    timeline: SemanticTimeline | Mapping[str, Any],
    *,
    behavior: Behavior,
    options: Mapping[str, Any] | None = None,
) -> EditDecisionList:
    """Small JSON-compatible adapter over ordinary deterministic EDL generators."""

    canonical = timeline if isinstance(timeline, SemanticTimeline) else SemanticTimeline.model_validate(timeline)
    values = dict(options or {})
    generators = {
        "silence": generate_silence_edl,
        "filler": generate_filler_edl,
        "false_start": generate_false_start_edl,
        "retake": generate_retake_edl,
        "pacing": generate_pacing_edl,
        "trim": generate_trim_edl,
        "reorder": generate_reorder_edl,
    }
    try:
        generator = generators[behavior]
    except KeyError as error:
        raise MCPValidationError("behavior", "must name a supported ordinary cleanup behavior") from error
    return generator(canonical, **values)
