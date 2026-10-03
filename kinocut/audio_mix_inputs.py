"""Bounded track descriptions shared by audio mixing operator adapters."""

from __future__ import annotations

import json
from typing import Any

from .engine_audio_mix import _TRACK_KEYS
from .engine_audio_validation import _audio_number
from .errors import MCPVideoError
from .limits import MAX_AUDIO_MIX_JSON_BYTES, MAX_AUDIO_MIX_TRACKS, MAX_AUDIO_MIX_VOLUME, MAX_VIDEO_DURATION


def _invalid(message: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code="invalid_parameter")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _invalid("sounds JSON must not repeat object keys")
        result[key] = value
    return result


def parse_mix_sounds(sounds: list[dict[str, Any]] | str, *, allow_json: bool = True) -> list[dict[str, Any]]:
    """Validate flat track descriptions; media/timeline checks stay in the engine."""
    try:
        if isinstance(sounds, str):
            if not allow_json:
                raise _invalid("sounds must be a track list")
            if len(sounds) > MAX_AUDIO_MIX_JSON_BYTES or len(sounds.encode("utf-8")) > MAX_AUDIO_MIX_JSON_BYTES:
                raise _invalid("sounds JSON exceeds its byte limit")
            sounds = json.loads(sounds, object_pairs_hook=_unique_object)
        if not isinstance(sounds, list) or not 1 <= len(sounds) <= MAX_AUDIO_MIX_TRACKS:
            raise _invalid(f"sounds must contain 1 to {MAX_AUDIO_MIX_TRACKS} track objects")
        for index, track in enumerate(sounds):
            if not isinstance(track, dict) or len(track) > len(_TRACK_KEYS) or set(track) - _TRACK_KEYS:
                raise _invalid(f"sounds[{index}] must use only {sorted(_TRACK_KEYS)}")
            path = track.get("path")
            if not isinstance(path, str) or not path:
                raise _invalid(f"sounds[{index}].path must be a non-empty string")
            if len(path) > MAX_AUDIO_MIX_JSON_BYTES or len(path.encode("utf-8")) > MAX_AUDIO_MIX_JSON_BYTES:
                raise _invalid("sounds JSON exceeds its byte limit")
            for key in ("start", "volume", "fade_in", "fade_out"):
                if key in track:
                    high = MAX_AUDIO_MIX_VOLUME if key == "volume" else MAX_VIDEO_DURATION
                    _audio_number(track[key], f"sounds[{index}].{key}", 0, high)
        size = 0
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(sounds):
            size += len(chunk.encode("utf-8"))
            if size > MAX_AUDIO_MIX_JSON_BYTES:
                raise _invalid("sounds JSON exceeds its byte limit")
        return sounds
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise _invalid("sounds must be valid UTF-8 JSON track descriptions") from exc
