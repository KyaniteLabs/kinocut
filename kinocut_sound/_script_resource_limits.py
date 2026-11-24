"""Private resource ceilings for script input contracts."""

from __future__ import annotations

from dataclasses import dataclass

from kinocut_sound.limits import (
    MAX_SCRIPT_BEATS_PER_SCENE,
    MAX_SCRIPT_EVENTS_PER_SCENE,
    MAX_SCRIPT_LINES_PER_SCENE,
    MAX_SCRIPT_TEXT_LENGTH_CHARS,
)


@dataclass(frozen=True)
class _ScriptLimits:
    lines: int = MAX_SCRIPT_LINES_PER_SCENE
    beats: int = MAX_SCRIPT_BEATS_PER_SCENE
    events: int = MAX_SCRIPT_EVENTS_PER_SCENE
    text: int = MAX_SCRIPT_TEXT_LENGTH_CHARS


SCRIPT_LIMITS = _ScriptLimits()
