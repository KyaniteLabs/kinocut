"""Private resource-ceiling checks for raw standalone script inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kinocut_sound.limits import (
    MAX_SCRIPT_BEATS_PER_SCENE,
    MAX_SCRIPT_EVENTS_PER_SCENE,
    MAX_SCRIPT_LINES_PER_SCENE,
    MAX_SCRIPT_SCENES,
    MAX_SCRIPT_TEXT_LENGTH_CHARS,
    MAX_SCRIPT_TURNS_PER_SCENE,
)


def _collection(value: object) -> list[Any] | tuple[Any, ...] | None:
    return value if isinstance(value, (list, tuple)) else None


def _contains_long_text(values: list[Any] | tuple[Any, ...] | None) -> bool:
    if values is None:
        return False
    return any(
        isinstance(item, Mapping)
        and isinstance(item.get("text"), str)
        and len(item["text"]) > MAX_SCRIPT_TEXT_LENGTH_CHARS
        for item in values
    )


def script_limit_violation(document: object, *, wf: bool = False) -> bool:
    """Return whether a raw generic or WF script exceeds a named ceiling."""
    if not isinstance(document, Mapping):
        return False
    scenes = _collection(document.get("scenes"))
    if scenes is None:
        return False
    if len(scenes) > MAX_SCRIPT_SCENES:
        return True

    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        if wf:
            turns = _collection(scene.get("turns"))
            if turns is not None and (
                len(turns) > MAX_SCRIPT_TURNS_PER_SCENE
                or len(turns) > MAX_SCRIPT_EVENTS_PER_SCENE
                or _contains_long_text(turns)
            ):
                return True
            continue

        lines = _collection(scene.get("lines"))
        beats = _collection(scene.get("beats", ()))
        line_count = len(lines) if lines is not None else 0
        beat_count = len(beats) if beats is not None else 0
        if (
            line_count > MAX_SCRIPT_LINES_PER_SCENE
            or beat_count > MAX_SCRIPT_BEATS_PER_SCENE
            or line_count + beat_count > MAX_SCRIPT_EVENTS_PER_SCENE
            or _contains_long_text(lines)
            or _contains_long_text(beats)
        ):
            return True
    return False
