"""Private deterministic identities for script-derived timeline cues."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

from kinocut_sound._canonical import canonical_digest


def bounded_pause_cue_id(kind: str, source_id: str) -> str:
    """Return a bounded deterministic pause cue id for one source object."""
    digest = canonical_digest({"kind": kind, "source_id": source_id}).removeprefix("sha256:")
    token = base64.b32encode(bytes.fromhex(digest)).decode("ascii").rstrip("=").lower()
    return f"pause_{token}"


def timeline_emitting_ids(
    *,
    scenes: Sequence[Any],
    parsed_lines: Sequence[Any],
    beats: Sequence[Any],
) -> tuple[str, ...]:
    """Return every cue id a parsed script can deterministically emit."""
    cue_ids = [item.cue_id for item in parsed_lines]
    cue_ids.extend(item.beat_id for item in beats)
    cue_ids.extend(
        bounded_pause_cue_id("line", item.line.line_id) for item in parsed_lines if item.pause_after_seconds > 0.0
    )
    cue_ids.extend(bounded_pause_cue_id("scene", scene.scene_id) for scene in scenes if scene.pause_after_seconds > 0.0)
    return tuple(cue_ids)
