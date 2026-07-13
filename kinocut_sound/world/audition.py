"""Audition contract and receipt for ambient bed review.

G16: bed-audition reels (``bed-audition``) are owned by the existing D41
implementation. M0 defines only a backend-neutral port contract; the S8 leaf
uses a *fake* D41 port (see :mod:`kinocut_sound.world.d41_port`) and this
audition contract. The real D41 binding waits for S13.

Audition is a *perceptual* QA activity: per the sonic-world design (§"Perceptual
QA"), music/ambience taste always requires human review. An audition receipt
therefore always carries ``human_review_required = True`` and never
auto-passes. The receipt exposes no host path, raw prompt, or credential —
only bounded ids and SHA-256 hashes.

Design references (sonic-world design):
* G16 — bed-audition reels (D41-owned; port contract only here).
* §"Perceptual QA" — ambience taste is never auto-passed.
* §"Receipt & Provenance" — receipts never leak absolute paths or raw text.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound.world._errors import world_error


class AuditionContext(FrozenModel):
    """Where and why an audition is requested (bounded ids only)."""

    reviewer_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    note_hash: Sha256 | None = None

    @field_validator("reviewer_id", "project_id", "episode_id")
    @classmethod
    def _ids_bounded(cls, value: str) -> str:
        return BoundedCode(value)


class AuditionRequest(FrozenModel):
    """One audition request: bed id plus optional layer ids and target duration."""

    bed_id: str = Field(min_length=1)
    context: AuditionContext
    layer_ids: tuple[str, ...] = ()
    target_duration_seconds: float | None = None
    reel_label: str = Field(min_length=1)

    @field_validator("bed_id", "reel_label")
    @classmethod
    def _codes_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("layer_ids")
    @classmethod
    def _layers_bounded_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("layer ids must be unique")
        return value

    @field_validator("target_duration_seconds")
    @classmethod
    def _duration_not_boolean(cls, value: float | None) -> float | None:
        if value is not None and isinstance(value, bool):
            raise ValueError("target_duration_seconds must not be a boolean")
        return value


@dataclass(frozen=True)
class AuditionReceipt:
    """Perceptual-QA receipt — always requires human review."""

    bed_id: str
    reel_label: str
    reel_descriptor_hash: Sha256
    reviewer_id: str
    human_review_required: bool
    warnings: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "bed_id": self.bed_id,
            "reel_label": self.reel_label,
            "reel_descriptor_hash": self.reel_descriptor_hash,
            "reviewer_id": self.reviewer_id,
            "human_review_required": self.human_review_required,
            "warnings": list(self.warnings),
        }

    def digest(self) -> Sha256:
        encoded = json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class AuditionContract:
    """Pure audition contract — produces a human-review receipt, never auto-passes.

    The contract does not call the real D41 ``bed-audition``; it computes a
    deterministic reel descriptor hash from the request and always sets
    ``human_review_required = True`` because ambience taste is perceptual QA.
    """

    def audition(self, request: AuditionRequest) -> AuditionReceipt:
        bed_id = BoundedCode(request.bed_id)
        reel_label = BoundedCode(request.reel_label)
        descriptor = self._reel_descriptor(request)
        warnings = self._warnings(request)
        return AuditionReceipt(
            bed_id=bed_id,
            reel_label=reel_label,
            reel_descriptor_hash=descriptor,
            reviewer_id=request.context.reviewer_id,
            human_review_required=True,
            warnings=warnings,
        )

    @staticmethod
    def _reel_descriptor(request: AuditionRequest) -> Sha256:
        payload = {
            "bed_id": request.bed_id,
            "reel_label": request.reel_label,
            "layer_ids": list(request.layer_ids),
            "target_duration_seconds": request.target_duration_seconds,
            "project_id": request.context.project_id,
            "episode_id": request.context.episode_id,
            "reviewer_id": request.context.reviewer_id,
            "note_hash": request.context.note_hash,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _warnings(request: AuditionRequest) -> tuple[str, ...]:
        if request.target_duration_seconds is not None and request.target_duration_seconds <= 0:
            raise world_error(
                "target_duration_seconds must be positive when supplied",
                "audition_invalid",
            )
        return ()
