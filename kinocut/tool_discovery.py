"""Deterministic discovery over caller-supplied tool metadata, without inference."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# Whole phrases point at existing public contracts; they do not imply that an
# optional backend is installed or that a planning tool executes the operation.
_PHRASE_TOOLS = {
    "remove filler words": ("video_timeline_edit_plan",),
    "remove ums": ("video_timeline_edit_plan",),
    "find pauses": ("video_audio_waveform", "video_ai_remove_silence"),
    "detect silence": ("video_audio_waveform", "video_ai_remove_silence"),
    "foreground segmentation": ("hyperframes_remove_background",),
    "remove background": ("hyperframes_remove_background",),
    "resume render": ("video_workflow_render",),
    "safe to publish": ("video_publish_gate", "video_release_checkpoint"),
    "change volume": ("audio_effects", "audio_compose", "video_normalize_audio"),
    "keep face in frame": ("video_visual_transform_plan",),
    "portrait": ("video_resize", "video_visual_transform_plan"),
    "captions": ("video_subtitles", "video_generate_subtitles", "video_ai_transcribe"),
    "speech to text": ("video_ai_transcribe", "hyperframes_transcribe"),
}
_STOP_WORDS = frozenset({"a", "an", "and", "for", "how", "i", "in", "is", "me", "my", "of", "the", "to", "with"})


def _tokens(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[^\W_]+", text.casefold()))


def discover_tools(query: str, tools: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Rank exact names, phrase aliases and lexical matches with stable ties.

    Preserve literal substring search (including public name-prefix searches).
    Multiword lexical matches must cover every meaningful query token so a
    shared generic word cannot turn an unrelated request into a recommendation.
    Results remain bounded by the supplied catalog; no model or network is used.
    """
    literal = query.strip().casefold()
    query_tokens = _tokens(literal) - _STOP_WORDS
    normalized = " " + " ".join(re.findall(r"[^\W_]+", literal)) + " "
    aliases: dict[str, int] = {}
    for phrase, names in _PHRASE_TOOLS.items():
        if f" {phrase} " in normalized:
            for position, name in enumerate(names):
                aliases[name] = min(position, aliases.get(name, position))
    ranked = []
    for tool in tools:
        name = str(tool["name"])
        if name == "search_tools" or not literal:
            continue
        description = str(tool.get("description") or "")
        lowered_name, lowered_description = name.casefold(), description.casefold()
        name_tokens, description_tokens = _tokens(name), _tokens(description)
        exact = literal == lowered_name
        alias = name in aliases
        name_match = literal in lowered_name
        description_match = literal in lowered_description
        complete = bool(query_tokens) and query_tokens <= name_tokens | description_tokens
        if not (exact or alias or name_match or description_match or complete):
            continue
        # Boolean priorities avoid blending different match kinds into a
        # misleading probability. Sort remaining matches by specificity/name.
        priority = (
            exact, alias, -aliases.get(name, 0), name_match, description_match,
            len(query_tokens & name_tokens), len(query_tokens & description_tokens),
        )
        item = {
            "name": name,
            "description": description.split("\n")[0].strip(),
            "required_params": list(tool.get("required_params") or ()),
        }
        ranked.append((priority, name, item))
    ranked.sort(key=lambda row: row[1])
    ranked.sort(key=lambda row: row[0], reverse=True)
    matches = [item for _, _, item in ranked]
    return {"success": True, "query": query, "count": len(matches), "tools": matches}
