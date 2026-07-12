"""``ProtectedElement`` with its element and duration policy sets (design §4.6).

A protected element binds an element type, an exact dependency fingerprint,
allowed operations, and an explicit duration policy. There is deliberately no
force flag: agents can never bypass protection.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from kinocut.contracts._common import RecordBase, Sha256


class ElementType(StrEnum):
    """The closed set of things that can be placed under protection."""

    SOURCE_ASSET = "source_asset"
    AUDIO_STREAM = "audio_stream"
    CLIP_RANGE = "clip_range"
    TIMELINE_RANGE = "timeline_range"
    GRAPHIC = "graphic"
    SUBTITLE_SET = "subtitle_set"
    TIMING_MAP = "timing_map"
    MIX = "mix"
    RENDER_PARAMETER_SET = "render_parameter_set"


class DurationPolicy(StrEnum):
    """Explicit duration handling; never implicit for a protected element."""

    PRESERVE = "preserve"
    PAD = "pad"
    LOOP = "loop"
    TRIM = "trim"
    SHORTEST = "shortest"


class ProtectedElement(RecordBase):
    """A dependency placed under human-authorized protection (design §4.6).

    There is intentionally no ``force``/``override``/``bypass`` field: a
    collision with a protected element can only be cleared by a new explicit
    human review decision, never by an agent-set flag.
    """

    record_kind: Literal["protected_element"] = "protected_element"

    element_type: ElementType
    dependency_fingerprint: Sha256
    allowed_operations: tuple[str, ...] = ()
    duration_policy: DurationPolicy
    # Protection is only ever cleared by an explicit human review decision,
    # referenced here by its canonical id — never an ad-hoc label or agent flag.
    human_approval_ref: Sha256
