"""Shared orchestration configuration for the shorts workflow.

The orchestrator (``kinocut.product.shorts``) consumes these strict models
verbatim; the CLI/MCP adapters are thin facades that translate caller
arguments into one of these objects. Splitting the configuration out of the
orchestrator keeps the orchestrator focused on plan lifecycle and lets the
two adapters share a single canonical schema.

Everything here is:

* **Strict** — ``extra="forbid"``, ``frozen=True``, ``allow_inf_nan=False``;
  unknown fields, mutation, and non-finite floats are rejected.
* **JSON-stable** — every model round-trips through
  ``model_dump(mode="json")`` with sorted keys + compact separators.
* **Decoupled from engines** — no FFmpeg, no project-store, no I/O. The
  orchestrator wires these values into existing engine seams without ever
  re-deriving them.

Two canonical platforms are supported: ``youtube_shorts`` (the
external-form ``youtube-shorts``) and ``instagram_reels`` (external-form
``instagram-reel``). Hyphen forms are the canonical *external* identifiers
serialised in plans, manifests, and CLI/MCP payloads; the underscore forms
match the existing :mod:`kinocut.product.clip_pipeline` literal. Callers
may pass either; :func:`normalise_platform` collapses them to the
underscore internal form so the existing pipeline layers receive their
expected literal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- Canonical external platform identifiers --------------------------------

ExternalPlatform = Literal["youtube-shorts", "instagram-reel"]
InternalPlatform = Literal["youtube_shorts", "instagram_reels"]

CANONICAL_EXTERNAL_PLATFORMS: tuple[str, ...] = ("youtube-shorts", "instagram-reel")
"""The two platforms the orchestrator recognises at every public surface.

Every external payload — CLI flags, MCP tool arguments, JSON manifests,
package metadata — MUST use these hyphenated identifiers. The internal
clip-pipeline layers consume the underscore form; the orchestrator's
:func:`normalise_platform` performs the conversion.
"""

_HYPHEN_TO_UNDERSCORE: Mapping[str, str] = {
    "youtube-shorts": "youtube_shorts",
    "instagram-reel": "instagram_reels",
}

_UNDERSCORE_TO_HYPHEN: Mapping[str, str] = {
    "youtube_shorts": "youtube-shorts",
    "instagram_reels": "instagram-reel",
}


def normalise_platform(value: str) -> str:
    """Return the underscore (internal) form for ``value``.

    Accepts either external hyphen form or internal underscore form; raises
    :class:`ValueError` for any unknown identifier so a silent typo cannot
    produce a misspelled render job.

    Examples
    --------
    >>> normalise_platform("youtube-shorts")
    'youtube_shorts'
    >>> normalise_platform("instagram_reels")
    'instagram_reels'
    """

    if not isinstance(value, str) or not value:
        raise ValueError(f"unknown platform {value!r}; expected one of {list(CANONICAL_EXTERNAL_PLATFORMS)}")
    if value in _HYPHEN_TO_UNDERSCORE:
        return _HYPHEN_TO_UNDERSCORE[value]
    if value in _UNDERSCORE_TO_HYPHEN:
        return value
    raise ValueError(f"unknown platform {value!r}; expected one of {list(CANONICAL_EXTERNAL_PLATFORMS)}")


def externalise_platform(value: str) -> str:
    """Return the hyphen (external) form for ``value``; raises on unknown."""

    if not isinstance(value, str) or not value:
        raise ValueError(f"unknown platform {value!r}")
    if value in _UNDERSCORE_TO_HYPHEN:
        return _UNDERSCORE_TO_HYPHEN[value]
    if value in _HYPHEN_TO_UNDERSCORE:
        return value
    raise ValueError(f"unknown platform {value!r}; expected one of {list(CANONICAL_EXTERNAL_PLATFORMS)}")


def normalise_platforms(values: Sequence[str]) -> tuple[str, ...]:
    """Normalise every platform in ``values`` and de-duplicate while preserving order."""

    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        internal = normalise_platform(value)
        if internal not in seen:
            seen.add(internal)
            out.append(internal)
    return tuple(out)


# --- Strict base -------------------------------------------------------------


class _StrictModel(BaseModel):
    """Frozen, unknown-field-rejecting base shared by every config model."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


# --- Restrained audio-finishing configuration --------------------------------


class AudioFinishingConfig(_StrictModel):
    """Evidence-backed audio-finishing knobs the orchestrator passes downstream.

    These are *configuration* — never a new workflow op. The values are
    carried on the plan so the render path can opt in without re-deriving
    them, but the orchestrator itself never executes any audio DSP.
    ``lufs`` is the integrated-loudness target the render path will
    normalise to via :func:`kinocut.engine_audio_normalize.normalize_audio`;
    ``fade_seconds`` is the symmetric clip-edge fade the render path
    currently applies after loudness normalisation. Each field maps to a
    concrete knob the orchestrator's render path consumes today; removed
    historical fields are deliberately omitted so the configuration
    never advertises behaviour the orchestrator cannot deliver.
    """

    # Only fields the orchestrator actively threads into the render path
    # are exposed here. Historical fields that no consumer wired up (true
    # peak / declick / noise reduction) were removed in favour of
    # ``evidence-backed controls''; the engine accepts more knobs but the
    # public configuration never promises behaviour it cannot deliver
    # through the orchestrator's current contract.
    lufs: float = Field(default=-14.0, ge=-36.0, le=-6.0)
    fade_seconds: float = Field(default=0.05, ge=0.0, le=2.0)


# --- Intake (source) configuration ------------------------------------------


class IntakeConfig(_StrictModel):
    """Intake-time knobs shared by the orchestrator and the adapters.

    ``min_duration_seconds``/``max_duration_seconds`` clamp the orchestrator's
    acceptance window; proposals outside that window are surfaced as
    review warnings rather than dropped silently. ``resolution_policy``
    declares how the orchestrator should respond to source videos whose
    resolution does not fit the platform's target frame: ``"reject"`` fails
    closed at intake; ``"warn"`` accepts the source and surfaces the
    mismatch as a review warning on every proposal.
    """

    min_duration_seconds: float = Field(default=15.0, gt=0.0)
    max_duration_seconds: float = Field(default=14400.0, gt=0.0)
    resolution_policy: Literal["reject", "warn"] = "warn"

    @model_validator(mode="after")
    def _validate_window(self) -> IntakeConfig:
        if self.max_duration_seconds <= self.min_duration_seconds:
            raise ValueError("max_duration_seconds must be strictly greater than min_duration_seconds")
        return self


# --- Render configuration ----------------------------------------------------


class RenderConfig(_StrictModel):
    """Render-time knobs the orchestrator records on every plan.

    The orchestrator itself does not execute renders: it records the
    options a future render call should honour so a re-run produces a
    byte-identical plan. ``burned_captions`` and ``captions_editable``
    record the canonical caption contract; ``audio`` carries the
    evidence-backed loudness and fade knobs the render path consumes
    today. Deliberately omitted: any knob whose only consumer was a
    removed visual branch (e.g. ``subject_reframe``). Strict
    ``extra="forbid"`` ensures legacy mappings that still carry the
    removed flag fail closed at validation time instead of silently
    no-oping.
    """

    burned_captions: bool = False
    captions_editable: bool = True
    audio: AudioFinishingConfig = Field(default_factory=AudioFinishingConfig)


# --- Top-level orchestrator configuration -----------------------------------


class ShortsConfig(_StrictModel):
    """The single configuration object the adapters hand to the orchestrator.

    The orchestrator accepts a :class:`ShortsConfig` (or a mapping of equal
    shape) at every entry point. ``platforms`` is normalised to the internal
    underscore form; ``output_dir`` is a project-local directory the
    orchestrator may create — it is NOT a posting path.
    """

    platforms: tuple[str, ...] = Field(default_factory=lambda: tuple(_HYPHEN_TO_UNDERSCORE.values()))
    min_clip_seconds: float = Field(default=15.0, gt=0.0)
    max_clip_seconds: float = Field(default=180.0, gt=0.0)
    intake: IntakeConfig = Field(default_factory=IntakeConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    output_dir: str | None = Field(default=None, min_length=1)
    resume_job_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _normalise_platforms_and_window(self) -> ShortsConfig:
        # Normalise platforms to the underscore form; external callers
        # typically pass the hyphen form. Fail closed on an unknown id.
        normalised = tuple(normalise_platform(p) for p in self.platforms)
        if not normalised:
            raise ValueError("shorts config requires at least one platform")
        if self.max_clip_seconds <= self.min_clip_seconds:
            raise ValueError("max_clip_seconds must be strictly greater than min_clip_seconds")
        # Preserve order while ensuring uniqueness.
        seen: set[str] = set()
        deduped: list[str] = []
        for platform in normalised:
            if platform not in seen:
                seen.add(platform)
                deduped.append(platform)
        # Pydantic frozen model — use object.__setattr__ for the assignment.
        object.__setattr__(self, "platforms", tuple(deduped))
        return self


def config_from_mapping(mapping: Mapping[str, Any] | None) -> ShortsConfig:
    """Build a :class:`ShortsConfig` from a mapping or use safe defaults.

    ``None`` returns the strict default — no platforms preset, full duration
    window, no output directory. ``mapping`` keys are the same as
    :class:`ShortsConfig`'s field names; unknown keys raise
    :class:`ValueError` via the strict base.
    """

    if mapping is None:
        return ShortsConfig()
    if isinstance(mapping, ShortsConfig):
        return mapping
    return ShortsConfig.model_validate(mapping)


__all__ = sorted(
    [
        "AudioFinishingConfig",
        "CANONICAL_EXTERNAL_PLATFORMS",
        "ExternalPlatform",
        "IntakeConfig",
        "InternalPlatform",
        "RenderConfig",
        "ShortsConfig",
        "config_from_mapping",
        "externalise_platform",
        "normalise_platform",
        "normalise_platforms",
    ]
)
