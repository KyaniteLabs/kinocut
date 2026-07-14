"""Labeled equal-duration bed audition reel under the real voice (#24).

Composes the governed one-shot :func:`audio_bed` mix policy over several
candidate music beds, producing one labeled audition reel: each candidate is
auditioned for an equal-duration section of the voice, ducked/normalized with
the *same* ship-level policy, then concatenated. Bed approval is never
auto-updated by an audition (design §5.4).

The pure planning layer (``plan_bed_audition``) is unit-tested everywhere; the
render layer (``render_bed_audition``) requires FFmpeg + immutable source
snapshots and is exercised by the CI-gated integration test, exactly like
``audio_bed``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kinocut.audio_bed_validation import validate_audio_bed_params
from kinocut.contracts._common import ValueObject
from kinocut.defaults import (
    DEFAULT_AUDIO_BED_DUCK_ATTACK_MS,
    DEFAULT_AUDIO_BED_DUCK_RATIO,
    DEFAULT_AUDIO_BED_DUCK_RELEASE_MS,
    DEFAULT_AUDIO_BED_DUCK_THRESHOLD,
    DEFAULT_AUDIO_BED_DURATION_TOLERANCE_SECONDS,
    DEFAULT_AUDIO_BED_FADE_IN,
    DEFAULT_AUDIO_BED_FADE_OUT,
    DEFAULT_AUDIO_BED_LOOP_CROSSFADE,
    DEFAULT_AUDIO_BED_MUSIC_VOLUME,
    DEFAULT_AUDIO_BED_TARGET_LUFS,
)
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffmpeg, _validate_input_path, _validate_output_path

_LABEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,62}$"
_MAX_CANDIDATES = 16


def _safe_label(value: str) -> str:
    import re

    if re.fullmatch(_LABEL_PATTERN, value) is None:
        raise MCPVideoError(
            "audition labels must be bounded identifiers", error_type="validation_error", code="invalid_label"
        )
    return value


class AuditionSection(ValueObject):
    """One labeled equal-duration bed section of the audition reel."""

    index: int = Field(ge=0)
    label: str
    music_path: str
    voice_start_seconds: float = Field(ge=0.0)
    voice_end_seconds: float = Field(ge=0.0)
    duration_seconds: float = Field(ge=0.0)


class AuditionPlan(ValueObject):
    """A validated, render-ready audition plan (no FFmpeg required to build)."""

    voice_source: str
    output_display_name: str
    section_seconds: float
    sections: tuple[AuditionSection, ...]
    mix_policy: dict[str, Any]

    @field_validator("output_display_name")
    @classmethod
    def _safe_display(cls, value: str) -> str:
        import re
        from kinocut.validation import AUDIO_BED_SAFE_DISPLAY_RE

        if AUDIO_BED_SAFE_DISPLAY_RE.fullmatch(value) is None:
            raise ValueError("output_display_name must be a bounded basename")
        if re.search(r"[^A-Za-z0-9_.-]", value):
            raise ValueError("output_display_name must be a bounded basename")
        return value


def _default_mix_policy(**overrides: Any) -> dict[str, Any]:
    """The shared ship-level mix policy (same constants as ``audio_bed``)."""

    policy = {
        "loop": True,
        "loop_crossfade": DEFAULT_AUDIO_BED_LOOP_CROSSFADE,
        "fade_in": DEFAULT_AUDIO_BED_FADE_IN,
        "fade_out": DEFAULT_AUDIO_BED_FADE_OUT,
        "target_lufs": DEFAULT_AUDIO_BED_TARGET_LUFS,
        "duck_threshold": DEFAULT_AUDIO_BED_DUCK_THRESHOLD,
        "duck_ratio": DEFAULT_AUDIO_BED_DUCK_RATIO,
        "duck_attack": DEFAULT_AUDIO_BED_DUCK_ATTACK_MS,
        "duck_release": DEFAULT_AUDIO_BED_DUCK_RELEASE_MS,
        "music_volume": DEFAULT_AUDIO_BED_MUSIC_VOLUME,
        "duration_tolerance": DEFAULT_AUDIO_BED_DURATION_TOLERANCE_SECONDS,
    }
    policy.update(overrides)
    return policy


def plan_bed_audition(
    voice_source: str,
    candidates: list[str],
    *,
    labels: list[str] | None = None,
    section_seconds: float,
    output_display_name: str = "audition",
    **mix_policy: Any,
) -> AuditionPlan:
    """Validate inputs and build an equal-duration labeled audition plan.

    Each candidate is auditioned over its own equal-duration section of the
    voice (``section_seconds`` long), starting at ``index * section_seconds``.
    Labels default to ``Bed 1 .. Bed N`` and must be unique bounded identifiers
    when supplied explicitly.
    """

    if not isinstance(candidates, list) or not candidates:
        raise MCPVideoError(
            "audition requires at least one candidate bed", error_type="validation_error", code="empty_candidates"
        )
    if len(candidates) > _MAX_CANDIDATES:
        raise MCPVideoError(
            f"audition supports at most {_MAX_CANDIDATES} candidates",
            error_type="validation_error",
            code="too_many_candidates",
        )
    voice_source = _validate_input_path(voice_source)
    candidate_paths = [_validate_input_path(p) for p in candidates]
    if len(set(candidate_paths)) != len(candidate_paths):
        raise MCPVideoError(
            "candidate beds must be distinct", error_type="validation_error", code="duplicate_candidate"
        )

    if labels is not None:
        if len(labels) != len(candidates):
            raise MCPVideoError(
                "labels must match the candidate count", error_type="validation_error", code="label_count_mismatch"
            )
        label_values = [_safe_label(lbl) for lbl in labels]
        if len(set(label_values)) != len(label_values):
            raise MCPVideoError(
                "audition labels must be unique", error_type="validation_error", code="duplicate_label"
            )
    else:
        label_values = [f"Bed {i + 1}" for i in range(len(candidates))]

    if not isinstance(section_seconds, (int, float)) or section_seconds <= 0:
        raise MCPVideoError(
            "section_seconds must be positive", error_type="validation_error", code="invalid_section_seconds"
        )

    policy = _default_mix_policy(**mix_policy)
    validate_audio_bed_params(
        loop=policy["loop"],
        loop_crossfade=policy["loop_crossfade"],
        fade_in=policy["fade_in"],
        fade_out=policy["fade_out"],
        target_lufs=policy["target_lufs"],
        duck_threshold=policy["duck_threshold"],
        duck_ratio=policy["duck_ratio"],
        duck_attack=policy["duck_attack"],
        duck_release=policy["duck_release"],
        music_volume=policy["music_volume"],
        duration_tolerance=policy["duration_tolerance"],
    )

    sections = tuple(
        AuditionSection(
            index=i,
            label=label_values[i],
            music_path=candidate_paths[i],
            voice_start_seconds=i * section_seconds,
            voice_end_seconds=(i + 1) * section_seconds,
            duration_seconds=section_seconds,
        )
        for i in range(len(candidate_paths))
    )
    return AuditionPlan(
        voice_source=voice_source,
        output_display_name=output_display_name,
        section_seconds=section_seconds,
        sections=sections,
        mix_policy=policy,
    )


class AuditionReceipt(BaseModel):
    """Edit-receipt v1 emitted by the bed-audition composition."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: int = 1
    receipt_kind: str = "edit"
    operation: str = "bed_audition"
    voice_content_sha256: str
    sections: tuple[dict[str, Any], ...]
    output_content_sha256: str
    output_duration_seconds: float = Field(ge=0.0)
    output_display_name: str
    warnings: tuple[str, ...] = ()
    human_review_required: bool = True
    receipt_sha256: str | None = None


def _file_sha256(path: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def render_bed_audition(
    plan: AuditionPlan,
    output_path: str,
    *,
    save_receipt: str | None = None,
) -> dict[str, Any]:
    """Render the audition reel. Requires FFmpeg + immutable source snapshots.

    For each section: extract the equal-duration voice slice, render a governed
    bed via :func:`audio_bed`, then concatenate the sections into one reel.
    """

    from kinocut.engine_audio_bed import audio_bed  # local import: heavy, FFmpeg-backed

    output_path = _validate_output_path(output_path)
    if save_receipt is not None:
        _validate_output_path(save_receipt)

    voice_hash = _file_sha256(plan.voice_source)
    section_outputs: list[str] = []
    section_records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        for section in plan.sections:
            voice_slice = os.path.join(tmp, f"voice_{section.index}.wav")
            _run_ffmpeg(
                [
                    "-y", "-loglevel", "error",
                    "-ss", str(section.voice_start_seconds),
                    "-t", str(section.duration_seconds),
                    "-i", plan.voice_source,
                    "-vn", "-acodec", "pcm_s16le",
                    voice_slice,
                ]
            )
            bed_out = os.path.join(tmp, f"bed_{section.index}.wav")
            audio_bed(
                voice_slice,
                section.music_path,
                bed_out,
                **plan.mix_policy,
            )
            section_outputs.append(bed_out)
            section_records.append(
                {
                    "index": section.index,
                    "label": section.label,
                    "music_content_sha256": _file_sha256(section.music_path),
                    "voice_start_seconds": section.voice_start_seconds,
                    "voice_end_seconds": section.voice_end_seconds,
                    "duration_seconds": section.duration_seconds,
                }
            )

        concat_list = os.path.join(tmp, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as handle:
            for path in section_outputs:
                safe = path.replace("'", r"\'")
                handle.write(f"file '{safe}'\n")
        _run_ffmpeg(
            ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", output_path]
        )

    from kinocut.ffmpeg_helpers import _run_ffprobe_json

    probe = _run_ffprobe_json(output_path)
    duration = float(probe.get("format", {}).get("duration") or 0.0)
    receipt = AuditionReceipt(
        voice_content_sha256=voice_hash,
        sections=tuple(section_records),
        output_content_sha256=_file_sha256(output_path),
        output_duration_seconds=duration,
        output_display_name=plan.output_display_name,
    )
    payload = receipt.model_dump(mode="json")
    if save_receipt is not None:
        Path(save_receipt).write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")
    return payload


def bed_audition(
    voice_source: str,
    candidates: list[str],
    output_path: str,
    *,
    labels: list[str] | None = None,
    section_seconds: float,
    output_display_name: str = "audition",
    save_receipt: str | None = None,
    **mix_policy: Any,
) -> dict[str, Any]:
    """Plan then render an audition reel in one call (convenience wrapper)."""

    plan = plan_bed_audition(
        voice_source,
        candidates,
        labels=labels,
        section_seconds=section_seconds,
        output_display_name=output_display_name,
        **mix_policy,
    )
    return render_bed_audition(plan, output_path, save_receipt=save_receipt)


__all__ = [
    "AuditionPlan",
    "AuditionReceipt",
    "AuditionSection",
    "bed_audition",
    "plan_bed_audition",
    "render_bed_audition",
]
