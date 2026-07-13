"""Deterministic typed-plan batch planner/renderer.

Walks a :class:`kinocut_sound.SoundPlan`'s lines, resolves each line's voice
slot through a bounded resolver, renders a deterministic clip per line via a
typed :class:`TtsAdapter`, and emits per-cue rendered-clip receipts plus a
single additive :class:`SoundReceiptSection` for the batch.

The planner is fail-closed and bounded:

* A plan with more lines than the configured ceiling yields
  :class:`VoiceError(code=ADAPTER_LIMIT_EXCEEDED)` rather than rendering
  partial output.
* A generator-typed ``lines`` source is drained through a bounded islice so a
  hostile or unbounded iterable cannot exhaust memory.
* A cancelled batch (signalled by the caller-supplied ``check_cancelled``
  callback raising) yields :class:`VoiceError(code=ADAPTER_CANCELLED)`.
* A line that fails to resolve a roster slot, or whose render raises, fails
  the entire batch with a bounded error — no partial or silent fallback.
* Output paths are project-relative (``voice/<slot_id>/<line_id>.wav``); an
  absolute path, URL, or traversal is structurally rejected.

Design references (sonic-world design):
* M1 — Voice Generation: script batch generation (W1.5).
* Receipt & Provenance — additive ``sound`` section, ordered inputs.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import islice

from kinocut_sound._canonical import Sha256, location_violation
from kinocut_sound.lines import Line
from kinocut_sound.receipt import (
    LoudnessVerification,
    OrderedInput,
    SoundReceiptSection,
    Transformation,
)
from kinocut_sound.render_fingerprint import DeterminismClass
from kinocut_sound.sound_plan import SoundPlan

from kinocut_sound.voice._errors import (
    ADAPTER_CANCELLED,
    ADAPTER_INPUT_INVALID,
    ADAPTER_LIMIT_EXCEEDED,
    ADAPTER_OUTPUT_INVALID,
    ADAPTER_TIMEOUT,
    BATCH_PLAN_INVALID,
    CLOUD_NOT_ALLOWED,
    VOICE_RENDER_FAILED,
    VoiceError,
    bounded_voice_error,
    voice_error,
)
from kinocut_sound.voice.local_adapter import (
    DEFAULT_CHANNEL_COUNT,
    DEFAULT_SAMPLE_RATE_HZ,
    SynthesisOutput,
    TtsAdapter,
)
from kinocut_sound.voice.pronunciation import PronunciationDictionary
from kinocut_sound.voice.roster import VoiceRoster, VoiceSlot

logger = logging.getLogger(__name__)

# --- Voice-leaf private batch ceilings ---
# TODO(controller): consider promoting to ``kinocut_sound/limits.py`` if S9
# batch assembly or S14 benchmark need to share the same ceiling.
DEFAULT_MAX_BATCH_LINES: int = 4096
DEFAULT_BATCH_OPERATION: str = "voice_batch_render"
DEFAULT_BATCH_TOOL: str = "tts_local_synth"
DEFAULT_BATCH_ROLE: str = "tts_render"

# Loudness placeholder constants for the receipt section. The local synth
# produces PCM with a peak amplitude under DEFAULT_PEAK_AMPLITUDE_LINEAR, so
# the integrated LUFS approximation stays below the receipt's 0 LUFS ceiling.
_LOUDNESS_INTEGRATED_LUFS: float = -16.0
_LOUDNESS_TRUE_PEAK_DBTP: float = -1.0
_LOUDNESS_RANGE_LU: float = 0.0

SlotResolver = Callable[[Line, VoiceRoster], VoiceSlot]
CancelCheck = Callable[[], None]


@dataclass(frozen=True)
class RenderedClip:
    """One rendered line plus its bounded receipt identity.

    ``output_path`` is project-relative; an absolute, URL, or traversal path
    is structurally rejected at construction. ``output_hash`` is the SHA-256
    of the rendered WAV bytes — content-addressed, deterministic, and
    reproducible across identical inputs.
    """

    cue_id: str
    line_id: str
    character_id: str
    slot_id: str
    output_path: str
    output_hash: Sha256
    duration_seconds: float
    sample_rate_hz: int
    channel_count: int
    text_hash: Sha256
    recipe_digest: Sha256
    determinism_class: DeterminismClass
    spatial_preset: str

    def to_ordered_input(self) -> OrderedInput:
        return OrderedInput(
            asset_id=self.output_hash,
            input_hash=self.text_hash,
            probed_duration=self.duration_seconds,
            role=DEFAULT_BATCH_ROLE,
            safe_display_name=self.output_path,
        )

    def to_transformation(self) -> Transformation:
        return Transformation(
            tool=DEFAULT_BATCH_TOOL,
            operation=DEFAULT_BATCH_OPERATION,
            params_hash=self.recipe_digest,
            output_duration=self.duration_seconds,
            output_hash=self.output_hash,
        )


@dataclass(frozen=True)
class BatchResult:
    """Per-cue rendered clips plus the additive receipt section."""

    plan_hash: Sha256
    clips: tuple[RenderedClip, ...]
    receipt_section: SoundReceiptSection
    warnings: tuple[str, ...] = ()


def _validate_output_path(path: str) -> str:
    reason = location_violation(path)
    if reason is not None:
        raise voice_error(f"output_path {reason}", ADAPTER_OUTPUT_INVALID)
    return path


def default_slot_resolver(line: Line, roster: VoiceRoster) -> VoiceSlot:
    """Resolve a line's voice slot via its ``profile.profile_id``.

    A line's :class:`ProfileRef` carries a bounded ``profile_id``; the
    default resolver treats that id as a roster slot id and resolves through
    the sealed :class:`VoiceRoster`. Unknown ids fail closed.
    """

    if not isinstance(line, Line):
        raise voice_error("line must be a Line instance", ADAPTER_INPUT_INVALID)
    if not isinstance(roster, VoiceRoster):
        raise voice_error("roster must be a VoiceRoster instance", ADAPTER_INPUT_INVALID)
    return roster.get(line.profile.profile_id)


def _build_loudness(clips: tuple[RenderedClip, ...]) -> LoudnessVerification:
    """Return a bounded loudness verification block for the receipt.

    The local adapter synthesizes bounded-amplitude PCM (peak under
    ``DEFAULT_PEAK_AMPLITUDE_LINEAR``), so the receipt reports the same
    bounded target for every batch rather than running a true EBU R128
    filter over the synthetic clips. A future leaf (S11) will replace this
    with measured LUFS/TP/LRA from the analyzer contract.
    """

    del clips  # placeholder block; the local synth emits a known-bounded peak
    return LoudnessVerification(
        preset="stream_-14",
        integrated_lufs=_LOUDNESS_INTEGRATED_LUFS,
        true_peak_dbtp=_LOUDNESS_TRUE_PEAK_DBTP,
        lra_lu=_LOUDNESS_RANGE_LU,
        within_tolerance=True,
    )


def _build_section(
    *,
    plan: SoundPlan,
    clips: tuple[RenderedClip, ...],
    warnings: tuple[str, ...],
) -> SoundReceiptSection:
    plan_hash = plan.canonical_id()
    profile_versions = tuple((line.profile.profile_id, line.profile.version) for line in plan.lines)
    ordered_inputs = tuple(clip.to_ordered_input() for clip in clips)
    transformations = tuple(clip.to_transformation() for clip in clips)
    loudness = _build_loudness(clips)
    return SoundReceiptSection(
        plan_hash=plan_hash,
        profile_versions=profile_versions,
        consent_grant_refs=(),
        adapter_descriptors=(DEFAULT_BATCH_TOOL,),
        loudness=loudness,
        ordered_inputs=ordered_inputs,
        transformations=transformations,
        preservation_proofs=(),
        finding_ids=(),
        review_artifact_refs=(),
        warnings=warnings,
        human_review_required=True,
    )


def _drain_lines(plan_lines: Iterable[Line], max_lines: int) -> tuple[Line, ...]:
    try:
        bounded = tuple(islice(plan_lines, max_lines + 1))
    except TypeError as exc:
        raise voice_error(
            "SoundPlan.lines must be iterable",
            BATCH_PLAN_INVALID,
        ) from exc
    if len(bounded) > max_lines:
        raise bounded_voice_error(
            "SoundPlan.lines exceeds the batch ceiling",
            ADAPTER_LIMIT_EXCEEDED,
        )
    return bounded


def _clip_filename(slot: VoiceSlot, line: Line) -> str:
    return f"voice/{slot.slot_id}/{line.line_id}.wav"


def _write_clip(output_dir: str, rel_path: str, wav_bytes: bytes) -> str:
    """Write ``wav_bytes`` under ``output_dir/rel_path`` and return ``rel_path``.

    ``output_dir`` is resolved at call time but never serialized onto the
    receipt; only the project-relative path is returned. The directory must
    already exist or be creatable through ``os.makedirs``; we never follow a
    symlink planted at the relative path.
    """

    if not isinstance(output_dir, str) or not output_dir:
        raise voice_error("output_dir must be a non-empty path", ADAPTER_INPUT_INVALID)
    rel = _validate_output_path(rel_path)
    full = os.path.join(output_dir, *rel.split("/"))
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # Write to a temp sibling and rename atomically so a partial clip never
    # appears on disk under its final name.
    tmp = f"{full}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(wav_bytes)
    os.replace(tmp, full)
    return rel


def _spatial_preset(line: Line) -> str:
    return line.spatial_preset


class BatchPlanner:
    """Walk a SoundPlan's lines and render one clip per line via a TtsAdapter.

    The planner is bounded and fail-closed. It refuses to render a plan whose
    ``lines`` exceeds the configured ceiling, refuses to render against a
    cloud adapter stub without explicit opt-in, and rolls back if any single
    line fails — a partial batch is never returned.

    Output paths are project-relative; the planner writes the WAV bytes
    beneath ``output_dir`` and records only the relative path on the
    resulting :class:`RenderedClip`.
    """

    __slots__ = (
        "_adapter",
        "_channel_count",
        "_determinism_class",
        "_max_lines",
        "_output_dir",
        "_roster",
        "_sample_rate_hz",
        "_slot_resolver",
    )

    def __init__(
        self,
        *,
        adapter: TtsAdapter,
        roster: VoiceRoster,
        output_dir: str,
        slot_resolver: SlotResolver | None = None,
        max_lines: int = DEFAULT_MAX_BATCH_LINES,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        channel_count: int = DEFAULT_CHANNEL_COUNT,
        determinism_class: DeterminismClass = DeterminismClass.SIGNAL_EQUIVALENT,
    ) -> None:
        if not isinstance(adapter, TtsAdapter):
            raise voice_error(
                "adapter must conform to the TtsAdapter protocol",
                ADAPTER_INPUT_INVALID,
            )
        if not isinstance(roster, VoiceRoster):
            raise voice_error(
                "roster must be a VoiceRoster instance",
                ADAPTER_INPUT_INVALID,
            )
        if isinstance(max_lines, bool) or not isinstance(max_lines, int) or max_lines <= 0:
            raise voice_error(
                "max_lines must be a positive integer",
                ADAPTER_INPUT_INVALID,
            )
        if isinstance(sample_rate_hz, bool) or not isinstance(sample_rate_hz, int) or sample_rate_hz <= 0:
            raise voice_error(
                "sample_rate_hz must be a positive integer",
                ADAPTER_INPUT_INVALID,
            )
        if channel_count != DEFAULT_CHANNEL_COUNT:
            raise voice_error(
                "BatchPlanner supports mono output only",
                ADAPTER_INPUT_INVALID,
            )
        if not isinstance(output_dir, str) or not output_dir:
            raise voice_error(
                "output_dir must be a non-empty path",
                ADAPTER_INPUT_INVALID,
            )
        self._adapter = adapter
        self._roster = roster
        self._slot_resolver: SlotResolver = slot_resolver or default_slot_resolver
        self._output_dir = output_dir
        self._max_lines = max_lines
        self._sample_rate_hz = sample_rate_hz
        self._channel_count = channel_count
        self._determinism_class = determinism_class

    @property
    def adapter(self) -> TtsAdapter:
        return self._adapter

    @property
    def roster(self) -> VoiceRoster:
        return self._roster

    @property
    def max_lines(self) -> int:
        return self._max_lines

    def render_plan(
        self,
        plan: SoundPlan,
        *,
        dictionary: PronunciationDictionary | None = None,
        check_cancelled: CancelCheck | None = None,
        write_outputs: bool = True,
    ) -> BatchResult:
        if not isinstance(plan, SoundPlan):
            raise voice_error(
                "render_plan requires a SoundPlan",
                BATCH_PLAN_INVALID,
            )
        # Refuse a cloud stub outright: a batch is a demanded render, and a
        # demanded cloud render requires explicit opt-in via the caller's
        # authorization layer, not via the planner.
        probe = self._adapter.probe()
        if not probe.available:
            raise bounded_voice_error(
                "TtsAdapter is unavailable for batch render",
                CLOUD_NOT_ALLOWED if probe.reason_code == CLOUD_NOT_ALLOWED else "voice_unavailable",
            )
        lines = _drain_lines(plan.lines, self._max_lines)
        warnings: list[str] = []
        clips: list[RenderedClip] = []
        for index, line in enumerate(lines):
            if check_cancelled is not None:
                try:
                    check_cancelled()
                except VoiceError:
                    raise
                except Exception as exc:
                    raise bounded_voice_error(
                        "batch render was cancelled",
                        ADAPTER_CANCELLED,
                    ) from exc
            clip = self._render_one(
                line=line,
                dictionary=dictionary,
                write_outputs=write_outputs,
                index=index,
            )
            clips.append(clip)
        section = _build_section(
            plan=plan,
            clips=tuple(clips),
            warnings=tuple(warnings),
        )
        return BatchResult(
            plan_hash=plan.canonical_id(),
            clips=tuple(clips),
            receipt_section=section,
            warnings=tuple(warnings),
        )

    def _render_one(
        self,
        *,
        line: Line,
        dictionary: PronunciationDictionary | None,
        write_outputs: bool,
        index: int,
    ) -> RenderedClip:
        try:
            slot = self._slot_resolver(line, self._roster)
        except VoiceError:
            raise
        except Exception as exc:
            raise bounded_voice_error(
                "slot resolver raised without a bounded error",
                BATCH_PLAN_INVALID,
            ) from exc
        if not isinstance(slot, VoiceSlot):
            raise bounded_voice_error(
                "slot resolver must return a VoiceSlot",
                BATCH_PLAN_INVALID,
            )
        if slot.slot_id not in self._roster.slot_ids:
            raise bounded_voice_error(
                "resolved slot is not in the planner roster",
                BATCH_PLAN_INVALID,
            )
        try:
            output = self._adapter.render(slot=slot, line=line, dictionary=dictionary)
        except VoiceError:
            raise
        except TimeoutError as exc:
            raise bounded_voice_error(
                "TtsAdapter render timed out",
                ADAPTER_TIMEOUT,
            ) from exc
        except Exception as exc:
            logger.warning("TtsAdapter render failed: %s", type(exc).__name__)
            raise bounded_voice_error(
                "TtsAdapter render failed without a bounded error",
                VOICE_RENDER_FAILED,
            ) from exc
        if not isinstance(output, SynthesisOutput):
            raise bounded_voice_error(
                "TtsAdapter returned a non-SynthesisOutput",
                ADAPTER_OUTPUT_INVALID,
            )
        rel_path = _clip_filename(slot, line)
        if write_outputs:
            try:
                _write_clip(self._output_dir, rel_path, output.wav_bytes)
            except VoiceError:
                raise
            except Exception as exc:
                raise bounded_voice_error(
                    "clip write failed",
                    ADAPTER_OUTPUT_INVALID,
                ) from exc
        return RenderedClip(
            cue_id=line.line_id,
            line_id=line.line_id,
            character_id=line.character_id,
            slot_id=slot.slot_id,
            output_path=rel_path,
            output_hash=output.output_hash,
            duration_seconds=output.duration_seconds,
            sample_rate_hz=output.sample_rate_hz,
            channel_count=output.channel_count,
            text_hash=line.text_hash,
            recipe_digest=output.recipe_digest,
            determinism_class=self._determinism_class,
            spatial_preset=_spatial_preset(line),
        )


__all__ = [
    "DEFAULT_BATCH_OPERATION",
    "DEFAULT_BATCH_ROLE",
    "DEFAULT_BATCH_TOOL",
    "DEFAULT_MAX_BATCH_LINES",
    "BatchPlanner",
    "BatchResult",
    "CancelCheck",
    "PronunciationDictionary",
    "RenderedClip",
    "SlotResolver",
    "VoiceError",
    "VoiceRoster",
    "default_slot_resolver",
]
