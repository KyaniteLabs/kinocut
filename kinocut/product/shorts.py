"""Shared human-gated orchestration for long-form stream repurposing."""

from __future__ import annotations

import hashlib
import json
import math
import os

import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..engine_audio_normalize import normalize_audio
from ..engine_edit import trim
from ..engine_probe import probe
from ..engine_resize import resize
from ..engine_thumbnail import thumbnail
from ..engine_subtitles import subtitles
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _build_ffmpeg_cmd, _run_ffmpeg
from ..limits import MAX_AI_TRANSCRIBE_DURATION
from .captions import CaptionConfig, WordTiming, build_caption_artifact
from .config import ShortsConfig, config_from_mapping, externalise_platform, normalise_platform
from .clip_pipeline import clip_moment
from .highlight_discovery import discover_highlights
from .models import CandidateMoment, HighlightDiscoveryConfig, TranscriptSegment, TranscriptWord
from .package import PackageConfig, PackageLineage, ThumbnailSpec, package_approved_clip


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class IntakeReport(_StrictModel):
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    audio_available: bool
    format: str | None = None
    problems: tuple[str, ...] = ()


class ReviewDecision(_StrictModel):
    candidate_id: str
    action: Literal["preview", "approve", "reject", "trim", "title_hook_edit", "sensitive_unsuitable"]
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    title: str | None = None
    hook: str | None = None
    sensitive: bool | None = None
    unsuitable: bool | None = None
    evidence_ref: str | None = None

    @model_validator(mode="after")
    def _validate_trim(self) -> ReviewDecision:
        if self.action == "trim" and (self.start is None or self.end is None or self.end <= self.start):
            raise ValueError("trim decisions require start < end")
        return self


class RenderRecord(_StrictModel):
    candidate_id: str
    platform: str
    output_path: str
    render_digest: str = Field(pattern=r"^[0-9a-f]{16}$")
    editable_subtitles: str
    thumbnail_path: str
    cache_hit: bool = False


class ShortsPlan(_StrictModel):
    schema_version: Literal[1] = 1
    job_id: str = Field(pattern=r"^shorts_[0-9a-f]{16}$")
    status: Literal["review_required", "reviewed", "rendered", "packaged"] = "review_required"
    project_dir: str
    output_dir: str
    intake: IntakeReport
    platforms: tuple[str, ...]
    config: dict[str, Any]
    transcript: tuple[TranscriptSegment, ...]
    proposals: tuple[CandidateMoment, ...]
    decisions: tuple[ReviewDecision, ...] = ()
    renders: tuple[RenderRecord, ...] = ()
    package_manifests: tuple[str, ...] = ()
    external_posting: bool = False
    transcript_words: tuple[TranscriptWord, ...] = ()


_PLAN_CACHE: dict[str, ShortsPlan] = {}


def _error(problem: str, *, code: str, cause: str, recovery: str) -> MCPVideoError:
    return MCPVideoError(
        f"Problem: {problem} Likely cause: {cause} Recovery: {recovery}",
        error_type="validation_error",
        code=code,
        suggested_action={"auto_fix": False, "description": recovery},
    )


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plan_path(plan: ShortsPlan) -> str:
    return os.path.join(plan.output_dir, f"{plan.job_id}.plan.json")


def _save(plan: ShortsPlan) -> ShortsPlan:
    os.makedirs(plan.output_dir, exist_ok=True)
    path = _plan_path(plan)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(plan.model_dump(mode="json"), handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    os.replace(tmp, path)
    _PLAN_CACHE[plan.job_id] = plan
    return plan


def _load(job_or_dir: str, *, candidate_id: str | None = None) -> ShortsPlan:
    """Resolve a saved plan by job id, file path, or directory.

    Mutating entry points (``shorts_propose``, ``shorts_review``,
    ``shorts_render``, ``shorts_package``) MUST resolve to exactly one plan.
    Selecting "the newest" by mtime is the bug class behind GLM A5: it
    silently overwrites a reviewer's expectation when more than one plan is
    visible in a project directory. We therefore fail closed with a
    structured error when the lookup matches multiple plans and require the
    caller to pass the exact job id or file path.
    """
    if job_or_dir in _PLAN_CACHE:
        plan = _PLAN_CACHE[job_or_dir]
        if candidate_id is not None and not any(p.candidate_id == candidate_id for p in plan.proposals):
            raise _error(
                "The candidate is not in the resolved plan.",
                code="shorts_candidate_not_found",
                cause=f"candidate_id={candidate_id!r} is not in the saved proposal set.",
                recovery="Use a candidate id from `shorts_plan` output.",
            )
        return plan
    path = Path(job_or_dir)
    candidates: list[Path]
    if path.is_file():
        candidates = [path]
    elif path.is_dir():
        candidates = sorted(path.glob("shorts_*.plan.json"))
        nested = path / "shorts"
        if nested.is_dir():
            candidates.extend(sorted(nested.glob("shorts_*.plan.json")))
    else:
        candidates = []
    if not candidates:
        raise _error(
            "The saved shorts plan could not be found.",
            code="shorts_plan_not_found",
            cause="The job id or project directory does not contain a plan receipt.",
            recovery="Run `kino shorts <input>` to create proposals, then retry with its job id.",
        )
    if len(candidates) > 1:
        raise _error(
            "Multiple saved shorts plans matched the lookup; refusing to pick one silently.",
            code="shorts_plan_ambiguous",
            cause=f"Found {len(candidates)} plan receipts under {job_or_dir!r}; the orchestrator never selects by mtime.",
            recovery="Pass the exact job id (e.g. 'shorts_<hex>') or the plan file path to disambiguate.",
        )
    item = candidates[0]
    plan = ShortsPlan.model_validate_json(item.read_text(encoding="utf-8"))
    _PLAN_CACHE[plan.job_id] = plan
    if candidate_id is not None and not any(p.candidate_id == candidate_id for p in plan.proposals):
        raise _error(
            "The candidate is not in the resolved plan.",
            code="shorts_candidate_not_found",
            cause=f"candidate_id={candidate_id!r} is not in the saved proposal set.",
            recovery="Use a candidate id from `shorts_plan` output.",
        )
    return plan


def _logprob_to_confidence(raw: Any) -> float | None:
    """Translate an ``avg_logprob`` value into ``[0.0, 1.0]`` confidence.

    Whisper emits non-positive log-likelihoods, so the correct conversion is
    ``exp(avg_logprob)``. The previous implementation used ``1 + avg_logprob``
    which is mathematically wrong (e.g. ``avg_logprob=-0.5`` -> ``0.5``) and
    silently manufactured a confidence the upstream model never produced.

    Returns ``None`` when ``raw`` is missing or non-numeric so downstream
    consumers see "unknown" rather than a fabricated value.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, math.exp(value)))


def _segments(payload: Any) -> tuple[TranscriptSegment, ...]:
    """Coerce a transcript payload into strict :class:`TranscriptSegment` objects.

    Confidence provenance rules:
    * If the upstream entry supplied an explicit ``confidence`` in ``[0.0, 1.0]``
      we honour it directly.
    * Otherwise we translate ``avg_logprob`` via ``exp(avg_logprob)`` and use
      that result.
    * If neither signal is available, ``confidence`` is left ``None`` — the
      orchestrator MUST NOT default to ``1.0`` because doing so would mask
      upstream silence and hide downstream caption flagging.
    """
    if payload is None:
        return ()
    result: list[TranscriptSegment] = []
    for index, item in enumerate(payload):
        if isinstance(item, TranscriptSegment):
            result.append(item)
            continue
        raw = dict(item)
        explicit_confidence = raw.get("confidence")
        confidence: float | None
        if explicit_confidence is None:
            confidence = _logprob_to_confidence(raw.get("avg_logprob"))
        else:
            try:
                explicit_value = float(explicit_confidence)
            except (TypeError, ValueError):
                confidence = _logprob_to_confidence(raw.get("avg_logprob"))
            else:
                confidence = (
                    max(0.0, min(1.0, explicit_value))
                    if 0.0 <= explicit_value <= 1.0
                    else _logprob_to_confidence(raw.get("avg_logprob"))
                )
        data = {
            "segment_id": raw.get("segment_id", f"seg_{index:06d}"),
            "start": raw.get("start"),
            "end": raw.get("end"),
            "text": str(raw.get("text", "")).strip(),
            "speaker": raw.get("speaker"),
            "confidence": confidence,
            "is_silence": bool(raw.get("is_silence", False)),
        }
        if not data["text"]:
            continue
        result.append(TranscriptSegment.model_validate(data))
    return tuple(sorted(result, key=lambda segment: (segment.start, segment.end, segment.segment_id)))


def _transcribe(
    source_path: str, *, duration: float, model: str = "base", language: str | None = None
) -> tuple[TranscriptSegment, ...]:
    """Run the underlying ASR engine and map the result to :class:`TranscriptSegment`.

    A2 note: this helper only returns segments so it stays a drop-in for the
    existing discovery layer. The full ``transcribe_longform`` result (with
    per-word timings) is captured separately by :func:`_transcribe_with_words`
    so the caption stage can use real Whisper timings instead of synthesizing
    them.
    """
    from ..ai_engine.transcribe import ai_transcribe
    from ..ai_engine.transcribe_longform import transcribe_longform

    try:
        if duration > MAX_AI_TRANSCRIBE_DURATION:
            longform = transcribe_longform(source_path, model=model, language=language)
            return _segments(segment.model_dump(mode="json") for segment in longform.segments)
        result = ai_transcribe(source_path, model=model, language=language)
    except MCPVideoError:
        raise
    except Exception as exc:
        raise _error(
            "The recording could not be transcribed.",
            code="shorts_transcription_failed",
            cause=str(exc),
            recovery="Install the local transcription extra or configure an opt-in provider, then resume the saved intake.",
        ) from exc
    return _segments(result.get("segments", ()))


class _TranscribedMedia:
    """Internal carrier for the segments + per-word timings produced by ASR.

    Plain tuple/dataclass shapes are the conventional carrier but a small
    named record makes the segment-to-word association self-documenting at
    the call sites that need it (currently the caption stage). The
    ``transcript_words`` is empty when the underlying engine did not emit
    word timings (e.g. ``ai_transcribe`` for short media) — the caption
    stage then falls back to even synthesis honestly, never synthesising a
    fabricated ``transcript_words`` list.
    """

    __slots__ = ("segments", "transcript_words")

    def __init__(
        self,
        segments: tuple[TranscriptSegment, ...],
        transcript_words: tuple[TranscriptWord, ...],
    ) -> None:
        self.segments = segments
        self.transcript_words = transcript_words


def _assign_segment_ids(segments: tuple[TranscriptSegment, ...]) -> dict[int, str]:
    """Return a mapping from list-position to segment_id for caption stitching.

    Position-based so the orchestrator never depends on Whisper's segment
    ``id`` field; downstream code looks the segment up by index because the
    ``LongformWord`` merger preserves order.
    """
    return {index: segment.segment_id for index, segment in enumerate(segments)}


def _attach_words_to_segments(
    segments: tuple[TranscriptSegment, ...],
    long_words: list[Any],
) -> tuple[TranscriptWord, ...]:
    """Map ``LongformWord`` records to their parent :class:`TranscriptSegment`.

    Whisper does not give us a stable ``segment_id`` for each word, and
    chunk indices are not 1:1 with merged segments (multiple segments share
    a chunk). The robust mapping is per-word time-overlap against the
    ordered merged segment list. Words that fall outside every segment (a
    Whisper edge case where ``word_timestamps=True`` emits a token after
    the segment's reported ``end``) are skipped honestly rather than
    attached to an unrelated segment.
    """
    if not long_words:
        return ()
    ordered = sorted(segments, key=lambda seg: seg.start)
    out: list[TranscriptWord] = []
    for long_word in long_words:
        word_text = long_word.word.strip()
        if not word_text:
            continue
        w_start = float(long_word.start)
        w_end = float(long_word.end)
        if w_end <= w_start:
            continue
        # Find the segment with the strongest overlap whose window contains
        # or substantially contains the word. Whisper's word timestamps are
        # always within the segment, so the first match in chronological
        # order is correct.
        matched_id: str | None = None
        for seg in ordered:
            if seg.end <= w_start:
                continue
            if seg.start > w_end:
                break
            matched_id = seg.segment_id
            break
        if matched_id is None:
            # Word outside every segment: skip rather than fabricate.
            continue
        out.append(
            TranscriptWord(
                word=word_text,
                start=w_start,
                end=w_end,
                segment_id=matched_id,
                probability=getattr(long_word, "probability", None),
                chunk_index=getattr(long_word, "chunk_index", None),
            )
        )
    return tuple(out)


def _transcribe_with_words(
    source_path: str, *, duration: float, model: str = "base", language: str | None = None
) -> _TranscribedMedia:
    """Run the ASR engine and capture both segments and real Whisper word timings.

    A2 fix: this is the entry point that preserves actual Whisper word
    timings through the orchestrator. The long-form path emits real
    ``LongformWord`` records with ``(word, start, end, probability)``; the
    short-form path emits no words because ``ai_transcribe`` does not expose
    them. The caption stage uses the result via ``_caption_for`` and falls
    back to even synthesis only when ``transcript_words`` is empty.
    """
    from ..ai_engine.transcribe import ai_transcribe
    from ..ai_engine.transcribe_longform import transcribe_longform

    try:
        if duration > MAX_AI_TRANSCRIBE_DURATION:
            longform = transcribe_longform(source_path, model=model, language=language)
            segments = _segments(segment.model_dump(mode="json") for segment in longform.segments)
            words = _attach_words_to_segments(segments, list(longform.words))
            return _TranscribedMedia(segments=segments, transcript_words=words)
        result = ai_transcribe(source_path, model=model, language=language)
    except MCPVideoError:
        raise
    except Exception as exc:
        raise _error(
            "The recording could not be transcribed.",
            code="shorts_transcription_failed",
            cause=str(exc),
            recovery="Install the local transcription extra or configure an opt-in provider, then resume the saved intake.",
        ) from exc
    segments = _segments(result.get("segments", ()))
    return _TranscribedMedia(segments=segments, transcript_words=())


def _config_from_flat(config: dict[str, Any]) -> ShortsConfig:
    nested = dict(config.pop("shorts_config", {}) or {})
    platforms = config.pop("platforms", None)
    if platforms is not None:
        nested["platforms"] = tuple(platforms)
    for key in ("min_clip_seconds", "max_clip_seconds", "output_dir", "resume_job_id"):
        if key in config and config[key] is not None:
            nested[key] = config.pop(key)
    render = dict(nested.get("render", {}) or {})
    for key in ("burned_captions", "captions_editable"):
        if key in config and config[key] is not None:
            render[key] = config.pop(key)
    if render:
        nested["render"] = render
    return config_from_mapping(nested)


def _dedupe_candidates(candidates: tuple[CandidateMoment, ...]) -> tuple[CandidateMoment, ...]:
    """Drop candidates whose time window substantially duplicates a stronger one."""
    kept: list[CandidateMoment] = []
    for candidate in candidates:
        duplicate = False
        for existing in kept:
            overlap = max(0.0, min(candidate.end, existing.end) - max(candidate.start, existing.start))
            shorter = min(candidate.end - candidate.start, existing.end - existing.start)
            if shorter > 0 and overlap / shorter >= 0.65:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return tuple(kept)


def shorts_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Inspect, transcribe, and propose moments; never render implicitly."""
    project_dir = kwargs.pop("project_dir", None)
    source_path = kwargs.pop("source_path", None)
    if args:
        source_path = args[0]
    if not isinstance(source_path, str) or not source_path:
        raise _error(
            "No recording was supplied.",
            code="shorts_source_required",
            cause="The source path is empty.",
            recovery="Pass a completed livestream recording path.",
        )

    raw_config = dict(kwargs.pop("config", {}) or {})
    raw_config.update(kwargs)
    transcript_payload = raw_config.pop("transcript_segments", None)
    model = str(raw_config.pop("model", "base"))
    language = raw_config.pop("language", None)
    cfg = _config_from_flat(raw_config)
    output_dir = os.path.realpath(cfg.output_dir or os.path.join(str(project_dir or os.getcwd()), "shorts"))

    if cfg.resume_job_id:
        persisted_path = os.path.join(output_dir, f"{cfg.resume_job_id}.plan.json")
        plan = _load(persisted_path if os.path.isfile(persisted_path) else cfg.resume_job_id)
        if _sha256(source_path) != plan.intake.source_sha256:
            raise _error(
                "The source changed since the saved job.",
                code="shorts_source_changed",
                cause="Its checksum no longer matches the intake receipt.",
                recovery="Restore the original recording or start a new shorts job.",
            )
        return plan.model_dump(mode="json")

    try:
        info = probe(source_path)
    except Exception as exc:
        if isinstance(exc, MCPVideoError):
            raise
        raise _error(
            "The recording could not be inspected.",
            code="shorts_intake_failed",
            cause=str(exc),
            recovery="Verify the file exists and can be opened by FFmpeg, then retry.",
        ) from exc
    if not info.audio_codec:
        raise _error(
            "The recording has no usable audio.",
            code="shorts_audio_missing",
            cause="No audio stream was detected.",
            recovery="Use a recording with an audio track or repair the source container.",
        )
    if not (cfg.intake.min_duration_seconds <= info.duration <= cfg.intake.max_duration_seconds):
        raise _error(
            "The recording duration is outside the configured intake range.",
            code="shorts_duration_unsupported",
            cause=f"Detected {info.duration:.1f}s; configured range is {cfg.intake.min_duration_seconds:.1f}-{cfg.intake.max_duration_seconds:.1f}s.",
            recovery="Choose a compatible recording or adjust the intake duration limits.",
        )

    transcript_words: tuple[TranscriptWord, ...]
    if transcript_payload is not None:
        transcript = _segments(transcript_payload)
        transcript_words = tuple(
            TranscriptWord(
                word=str(raw.get("word", "")).strip(),
                start=float(raw.get("start", 0.0)),
                end=float(raw.get("end", raw.get("start", 0.0))),
                segment_id=str(raw.get("segment_id", "")),
                probability=raw.get("probability"),
                chunk_index=raw.get("chunk_index"),
            )
            for raw in (dict(item) for item in transcript_payload)
            if str(raw.get("word", "")).strip()
            and float(raw.get("end", 0.0)) > float(raw.get("start", 0.0))
            and str(raw.get("segment_id", ""))
        )
    else:
        media = _transcribe_with_words(source_path, duration=info.duration, model=model, language=language)
        transcript = media.segments
        transcript_words = media.transcript_words
    if not transcript:
        raise _error(
            "Transcription produced no spoken segments.",
            code="shorts_empty_transcript",
            cause="The recording may be silent or the selected language/model could not recognize it.",
            recovery="Check the audio and transcription settings, then retry.",
        )
    discovery = discover_highlights(
        transcript,
        config=HighlightDiscoveryConfig(min_duration=cfg.min_clip_seconds, max_duration=cfg.max_clip_seconds),
    )
    proposals = _dedupe_candidates(discovery.candidates)
    if not proposals:
        raise _error(
            "No complete clip candidates were found.",
            code="shorts_no_candidates",
            cause="The transcript lacks a complete thought within the target duration.",
            recovery="Adjust clip duration settings or supply a clearer transcript.",
        )

    intake = IntakeReport(
        source_path=os.path.realpath(source_path),
        source_sha256=_sha256(source_path),
        duration=info.duration,
        width=info.width,
        height=info.height,
        audio_available=True,
        format=info.format,
        problems=(
            () if info.width >= 720 else ("source resolution is below 720p; safe padded composition will be used",)
        ),
    )
    config_json = cfg.model_dump(mode="json")
    seed = json.dumps({"source": intake.source_sha256, "config": config_json}, sort_keys=True, separators=(",", ":"))
    job_id = f"shorts_{hashlib.sha256(seed.encode()).hexdigest()[:16]}"
    plan = ShortsPlan(
        job_id=job_id,
        project_dir=os.path.realpath(str(project_dir or output_dir)),
        output_dir=output_dir,
        intake=intake,
        platforms=tuple(externalise_platform(p) for p in cfg.platforms),
        config=config_json,
        transcript=transcript,
        proposals=proposals,
        transcript_words=transcript_words,
    )

    return _save(plan).model_dump(mode="json")


_VALID_REVIEW_ACTIONS: frozenset[str] = frozenset(ReviewDecision.model_fields["action"].annotation.__args__)


def _validate_review_action(action: Any) -> str:
    """Normalise + validate a review action for both propose and review.

    A9 fix: ``shorts_propose`` previously inferred an action and let
    pydantic raise a generic validation error if it was unknown; ``shorts_review``
    hand-rolled the same membership check with a different error code. The
    error codes were inconsistent and the error messages differed. This
    helper is the single source of truth so both surfaces report the same
    plain-language error and code when an action is unsupported.
    """
    if action is None:
        raise _error(
            "The review action is required.",
            code="shorts_review_invalid",
            cause="No action was supplied.",
            recovery="Use preview, approve, reject, trim, title_hook_edit, or sensitive_unsuitable.",
        )
    candidate = str(action)
    if candidate not in _VALID_REVIEW_ACTIONS:
        raise _error(
            "The review action is not supported.",
            code="shorts_review_invalid",
            cause=f"Unknown action {candidate!r}.",
            recovery="Use preview, approve, reject, trim, title_hook_edit, or sensitive_unsuitable.",
        )
    return candidate


def shorts_propose(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply non-rendering candidate edits and return the revised plan."""
    plan_payload = kwargs.pop("plan", None)
    project_dir = kwargs.pop("project_dir", None)
    candidate_id = kwargs.pop("candidate_id", None)
    edits = kwargs.pop("edits", None) or kwargs.pop("edit", None) or {}
    job_id = None
    if args:
        job_id = args[0]
    if len(args) > 1:
        candidate_id = args[1]
    plan = (
        ShortsPlan.model_validate(plan_payload)
        if plan_payload is not None
        else _load(str(job_id or project_dir), candidate_id=candidate_id)
    )
    if not candidate_id or not any(p.candidate_id == candidate_id for p in plan.proposals):
        raise _error(
            "The candidate does not exist.",
            code="shorts_candidate_not_found",
            cause="Its id is not in the saved proposal set.",
            recovery="Use a candidate id from `shorts_propose` output.",
        )
    action = _validate_review_action(
        edits.pop(
            "action",
            "trim" if "start" in edits or "end" in edits else "title_hook_edit",
        )
    )
    decision = ReviewDecision(candidate_id=candidate_id, action=action, **edits)
    revised = plan.model_copy(update={"decisions": (*plan.decisions, decision), "status": "reviewed"})
    return _save(revised).model_dump(mode="json")


def shorts_review(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Append an explicit human decision without rendering."""
    project_dir = kwargs.pop("project_dir", None)
    candidate_id = kwargs.pop("candidate_id", None)
    decision_payload = kwargs.pop("decision", None)
    evidence_ref = kwargs.pop("evidence_ref", None)
    job_id = None
    if args:
        job_id = args[0]
    if len(args) > 1:
        candidate_id = args[1]
    if len(args) > 2:
        decision_payload = args[2]
    plan = _load(str(job_id or project_dir), candidate_id=candidate_id)
    payload = dict(decision_payload) if isinstance(decision_payload, dict) else {"action": str(decision_payload)}
    action = _validate_review_action(payload.pop("action", payload.pop("decision", None)))
    record = ReviewDecision(candidate_id=str(candidate_id), action=action, evidence_ref=evidence_ref, **payload)
    revised = plan.model_copy(update={"decisions": (*plan.decisions, record), "status": "reviewed"})
    saved = _save(revised)
    return {
        "job_id": saved.job_id,
        "proposal_id": candidate_id,
        "decisions": [d.model_dump(mode="json") for d in saved.decisions],
        "status": saved.status,
    }


def _effective_candidate(plan: ShortsPlan, candidate_id: str) -> CandidateMoment:
    candidate = next((item for item in plan.proposals if item.candidate_id == candidate_id), None)
    if candidate is None:
        raise _error(
            "The candidate does not exist.",
            code="shorts_candidate_not_found",
            cause="Its id is not in the plan.",
            recovery="Choose a candidate from the proposal output.",
        )
    updates: dict[str, Any] = {}
    approved = False
    for decision in plan.decisions:
        if decision.candidate_id != candidate_id:
            continue
        if decision.action == "reject":
            approved = False
        elif decision.action == "approve":
            approved = True
        elif decision.action == "trim":
            updates.update(start=decision.start, end=decision.end)
        elif decision.action == "title_hook_edit":
            if decision.title:
                updates["suggested_title"] = decision.title
            if decision.hook:
                updates["suggested_hook"] = decision.hook
        elif decision.action == "sensitive_unsuitable" and decision.unsuitable:
            updates.update(unsuitable=True, sensitivity="unsafe")
    candidate = candidate.model_copy(update=updates)
    if not approved:
        raise _error(
            "The candidate is not approved for rendering.",
            code="shorts_review_required",
            cause="No current human approval exists.",
            recovery="Record an approve decision after reviewing the candidate.",
        )
    if candidate.unsuitable:
        raise _error(
            "The candidate is marked unsuitable.",
            code="shorts_candidate_unsuitable",
            cause="Human review flagged sensitive material.",
            recovery="Choose another candidate or record a deliberate revised review decision.",
        )
    return candidate


def _even_synthesized_words(plan: ShortsPlan, candidate: CandidateMoment) -> list[WordTiming]:
    """Fallback caption words evenly spread across each overlapping segment.

    Used only when ``plan.transcript_words`` is empty (e.g. legacy plans or
    the short-form ``ai_transcribe`` path that does not expose word
    timings). The synthesizer splits the segment duration evenly across the
    tokens in its ``text`` field so caption rendering can still produce a
    valid SRT when no real timings exist. Confidence defaults to ``None``
    rather than ``1.0`` so the caption stage can mark the cue as unknown
    instead of pretending to know the per-word probability.
    """
    overlapping = [s for s in plan.transcript if s.end > candidate.start and s.start < candidate.end]
    words: list[WordTiming] = []
    for segment in overlapping:
        tokens = segment.text.split()
        if not tokens:
            continue
        step = (segment.end - segment.start) / len(tokens)
        for index, token in enumerate(tokens):
            global_start = segment.start + index * step
            global_end = segment.start + (index + 1) * step
            if global_end <= candidate.start or global_start >= candidate.end:
                continue
            word_start = max(global_start, candidate.start) - candidate.start
            word_end = min(global_end, candidate.end) - candidate.start
            words.append(
                WordTiming(
                    word=token,
                    start=word_start,
                    end=max(word_end, word_start + 0.001),
                    probability=segment.confidence,
                )
            )
    return words


def _real_word_timings(plan: ShortsPlan, candidate: CandidateMoment) -> list[WordTiming]:
    """Build caption words from real Whisper timings preserved on the plan.

    A2 fix: when the long-form transcription path produced per-word timings
    we keep them through the orchestrator and feed them into the caption
    grouper instead of falling back to even synthesis. ``WordTiming.probability``
    is the per-word value (``None`` when Whisper did not emit one) so the
    caption stage's confidence-flagging can act on real signal rather than
    a synthesised default.
    """
    if not plan.transcript_words:
        return []
    overlapping_ids = {
        seg.segment_id for seg in plan.transcript if seg.end > candidate.start and seg.start < candidate.end
    }
    words: list[WordTiming] = []
    for transcript_word in plan.transcript_words:
        if transcript_word.segment_id not in overlapping_ids:
            continue
        if transcript_word.end <= candidate.start or transcript_word.start >= candidate.end:
            continue
        word_start = max(transcript_word.start, candidate.start) - candidate.start
        word_end = min(transcript_word.end, candidate.end) - candidate.start
        if word_end <= word_start:
            word_end = word_start + 0.001
        words.append(
            WordTiming(
                word=transcript_word.word,
                start=word_start,
                end=word_end,
                probability=transcript_word.probability,
            )
        )
    return words


def _caption_for(plan: ShortsPlan, candidate: CandidateMoment):
    """Generate the caption artifact for a candidate.

    Prefers real Whisper word timings preserved on the plan via
    ``transcript_words``; falls back to even synthesis ONLY when no real
    timings are available. ``probability`` is always the actual value from
    upstream — never a synthesised ``1.0`` — so the caption stage's
    low-confidence policy can act on truthful signal.
    """
    words = _real_word_timings(plan, candidate) or _even_synthesized_words(plan, candidate)
    return build_caption_artifact(words, config=CaptionConfig())


def shorts_render(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Render approved vertical drafts using existing trim/resize/audio engines."""
    project_dir = kwargs.pop("project_dir", None)
    candidate_id = kwargs.pop("candidate_id", None)
    output_path = kwargs.pop("output_path", None)
    render_options = dict(kwargs.pop("render_options", {}) or {})
    job_id = None
    if args:
        job_id = args[0]
    if len(args) > 1:
        candidate_id = args[1]
    plan = _load(str(job_id or project_dir), candidate_id=candidate_id)
    candidate = _effective_candidate(plan, str(candidate_id))
    base_dir = os.path.realpath(output_path or os.path.join(plan.output_dir, candidate.candidate_id))
    if os.path.splitext(base_dir)[1]:
        base_dir = os.path.dirname(base_dir)
    os.makedirs(base_dir, exist_ok=True)
    records: list[RenderRecord] = list(plan.renders)
    emitted: list[dict[str, Any]] = []
    candidate_digest = hashlib.sha256(
        json.dumps(candidate.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()[:16]
    review_warnings: list[str] = []
    for platform in plan.platforms:
        platform_dir = os.path.join(base_dir, platform)
        os.makedirs(platform_dir, exist_ok=True)
        final_path = os.path.join(platform_dir, "vertical.mp4")
        # ``plan.platforms`` carries the canonical external (hyphenated)
        # identifier (``youtube-shorts`` / ``instagram-reel``). The
        # clip_pipeline layer consumes the internal underscore form and
        # owns the per-platform maximum duration; external identifiers
        # never reach it. The candidate's original ``start``/``end`` are
        # left untouched on the plan so the review history and proposals
        # remain truthful about what was approved.
        internal_platform = normalise_platform(platform)
        clipped = clip_moment(candidate, platform=internal_platform)
        effective_start = clipped.start_seconds
        effective_end = clipped.end_seconds
        rendered_candidate = candidate.model_copy(update={"start": effective_start, "end": effective_end})
        if clipped.was_clipped or clipped.review_warning is not None:
            warning = clipped.review_warning or (
                f"moment {candidate.candidate_id!r} clipped to "
                f"{internal_platform} maximum "
                f"({effective_end - effective_start:.3f}s from original "
                f"{candidate.end - candidate.start:.3f}s)"
            )
            review_warnings.append(warning)
        digest = hashlib.sha256(
            (
                f"render-v5:{plan.intake.source_sha256}:{candidate_digest}:"
                f"{platform}:{effective_start}:{effective_end}:{plan.config}"
            ).encode()
        ).hexdigest()[:16]
        previous = next(
            (
                r
                for r in records
                if r.candidate_id == candidate.candidate_id
                and r.platform == platform
                and r.render_digest == digest
                and os.path.exists(r.output_path)
            ),
            None,
        )
        if previous:
            previous_payload = previous.model_copy(update={"cache_hit": True}).model_dump(mode="json")
            previous_payload.update(
                {
                    "effective_start_seconds": effective_start,
                    "effective_end_seconds": effective_end,
                    "original_start_seconds": clipped.original_start_seconds,
                    "original_end_seconds": clipped.original_end_seconds,
                    "was_clipped": clipped.was_clipped,
                    "review_warning": clipped.review_warning,
                }
            )
            emitted.append(previous_payload)
            continue
        trimmed = trim(
            plan.intake.source_path,
            start=effective_start,
            duration=effective_end - effective_start,
            output_path=os.path.join(platform_dir, "trimmed.mp4"),
        )
        vertical = resize(
            trimmed.output_path, aspect_ratio="9:16", output_path=os.path.join(platform_dir, "vertical-raw.mp4")
        )
        audio_cfg = plan.config.get("render", {}).get("audio", {})
        fade_seconds = float(audio_cfg.get("fade_seconds", 0.05))
        fade_out_start = max(0.0, effective_end - effective_start - fade_seconds)
        faded_path = os.path.join(platform_dir, "vertical-faded.mp4")
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                vertical.output_path,
                output_path=faded_path,
                video_codec="copy",
                audio_filter=f"afade=t=in:st=0:d={fade_seconds:.3f},afade=t=out:st={fade_out_start:.3f}:d={fade_seconds:.3f}",
            )
        )
        normalized = normalize_audio(
            faded_path,
            target_lufs=float(audio_cfg.get("lufs", -14.0)),
            output_path=final_path,
        )
        finished_path = normalized.output_path
        # Captions must use the effective platform-clipped window so subtitle
        # cues never extend beyond the rendered draft.
        caption = _caption_for(plan, rendered_candidate)
        srt_path = os.path.join(platform_dir, "captions.srt")
        Path(srt_path).write_text(
            caption.srt_body + ("" if caption.srt_body.endswith("\n") else "\n"), encoding="utf-8"
        )
        if plan.config.get("render", {}).get("burned_captions", False):
            burned = subtitles(
                finished_path,
                srt_path,
                output_path=os.path.join(platform_dir, "vertical-burned.mp4"),
            )
            finished_path = burned.output_path
        thumb_path = thumbnail(finished_path, output_path=os.path.join(platform_dir, "thumbnail.jpg")).output_path
        record = RenderRecord(
            candidate_id=candidate.candidate_id,
            platform=platform,
            output_path=finished_path,
            render_digest=digest,
            editable_subtitles=srt_path,
            thumbnail_path=thumb_path,
        )
        records = [r for r in records if not (r.candidate_id == candidate.candidate_id and r.platform == platform)] + [
            record
        ]
        emitted_payload = record.model_dump(mode="json")
        emitted_payload.update(
            {
                "effective_start_seconds": effective_start,
                "effective_end_seconds": effective_end,
                "original_start_seconds": clipped.original_start_seconds,
                "original_end_seconds": clipped.original_end_seconds,
                "was_clipped": clipped.was_clipped,
                "review_warning": clipped.review_warning,
            }
        )
        emitted.append(emitted_payload)
    revised = plan.model_copy(update={"renders": tuple(records), "status": "rendered"})
    _save(revised)
    return {
        "job_id": plan.job_id,
        "candidate_id": candidate.candidate_id,
        "status": "rendered",
        "renders": emitted,
        "external_posting": False,
        "render_options": render_options,
        "review_warnings": tuple(dict.fromkeys(review_warnings)),
    }


def shorts_package(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Create complete manual-publishing packages for an approved clip."""
    project_dir = kwargs.pop("project_dir", None)
    candidate_id = kwargs.pop("candidate_id", None)
    package_dir = kwargs.pop("package_dir", None)
    job_id = None
    if args:
        job_id = args[0]
    if len(args) > 1:
        candidate_id = args[1]
    plan = _load(str(job_id or project_dir), candidate_id=candidate_id)
    candidate = _effective_candidate(plan, str(candidate_id))
    relevant = [r for r in plan.renders if r.candidate_id == candidate.candidate_id]
    if not relevant:
        raise _error(
            "No rendered drafts exist for this candidate.",
            code="shorts_render_required",
            cause="Packaging was requested before render completed.",
            recovery="Run shorts_render for the approved candidate first.",
        )
    root = os.path.realpath(package_dir or os.path.join(plan.output_dir, candidate.candidate_id, "packages"))
    manifests: list[str] = list(plan.package_manifests)
    results: list[dict[str, Any]] = []
    review_warnings: list[str] = []
    for record in relevant:
        target = os.path.join(root, record.platform)
        os.makedirs(target, exist_ok=True)
        packaged_video = os.path.join(target, "vertical.mp4")
        packaged_thumbnail = os.path.join(target, "thumbnail.jpg")
        shutil.copy2(record.output_path, packaged_video)
        shutil.copy2(record.thumbnail_path, packaged_thumbnail)
        # Recompute the clipped bounds so the package manifest carries an
        # explicit truncation review warning whenever the platform cap
        # shortened the approved candidate. The plan's ``proposals`` and
        # ``decisions`` retain the original candidate timestamps, so a
        # reviewer can still audit what was approved vs. what was rendered.
        clipped = clip_moment(candidate, platform=normalise_platform(record.platform))
        packaged_candidate = candidate.model_copy(update={"start": clipped.start_seconds, "end": clipped.end_seconds})
        caption = _caption_for(plan, packaged_candidate)
        record_warnings: list[str] = []
        if clipped.was_clipped or clipped.review_warning is not None:
            warning = clipped.review_warning or (
                f"manifest inherits clipped bounds: "
                f"original [{clipped.original_start_seconds:.3f}, "
                f"{clipped.original_end_seconds:.3f}] -> effective "
                f"[{clipped.start_seconds:.3f}, {clipped.end_seconds:.3f}]"
            )
            record_warnings.append(warning)
            review_warnings.append(warning)
        result = package_approved_clip(
            package_dir=target,
            vertical_video_path=packaged_video,
            caption_artifact=caption,
            candidate=packaged_candidate,
            thumbnail=ThumbnailSpec(
                image_path=packaged_thumbnail,
                timestamp=(clipped.end_seconds - clipped.start_seconds) / 2,
            ),
            lineage=PackageLineage(
                candidate_id=candidate.candidate_id,
                transcript_reference=plan.intake.source_sha256,
                review_decision_ref=record.render_digest,
            ),
            extra_review_warnings=record_warnings,
            config=PackageConfig(overwrite_manifest=True),
        )
        manifests.append(result.manifest_path)
        results.append(result.model_dump(mode="json"))
    revised = plan.model_copy(update={"package_manifests": tuple(dict.fromkeys(manifests)), "status": "packaged"})
    _save(revised)
    return {
        "job_id": plan.job_id,
        "candidate_id": candidate.candidate_id,
        "status": "packaged",
        "packages": results,
        "external_posting": False,
        "review_warnings": tuple(dict.fromkeys(review_warnings)),
    }


def load_shorts_plan(job_or_path: str) -> ShortsPlan:
    return _load(job_or_path)


__all__ = [
    "IntakeReport",
    "RenderRecord",
    "ReviewDecision",
    "ShortsPlan",
    "load_shorts_plan",
    "shorts_package",
    "shorts_plan",
    "shorts_propose",
    "shorts_render",
    "shorts_review",
]
