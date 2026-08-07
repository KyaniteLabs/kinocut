"""Canonical intent verbs exposed via video_intent (P2.5)."""

from __future__ import annotations

from typing import Any, Final

# ~10 semantic verbs. Full MCP surface remains as depth/compat.
INTENT_VERBS: Final[dict[str, dict[str, Any]]] = {
    "remove_silence": {
        "summary": "Cut long silences from speech (reviewable EDL / AI silence path).",
        "async_preferred": True,
        "mutates_media": True,
        "compat_tools": ("video_ai_remove_silence",),
    },
    "remove_filler": {
        "summary": "Filler/restart phrase removal with human-reviewable cuts.",
        "async_preferred": True,
        "mutates_media": True,
        "compat_tools": ("video_find_moments",),
        "notes": "Uses projectstore disfluency + semantic generators; never silent auto-cut.",
    },
    "reformat_vertical": {
        "summary": "Speaker-aware 9:16 reframe with subject tracking.",
        "async_preferred": True,
        "mutates_media": True,
        "compat_tools": ("video_resize",),
        "params": {"subject_tracking": "auto"},
    },
    "cut_to_beats": {
        "summary": "Align cuts to audio beats / bed tempo markers.",
        "async_preferred": True,
        "mutates_media": True,
        "compat_tools": ("video_edit", "sound_plan_validate"),
    },
    "inject_broll": {
        "summary": "Propose transcript-keyed b-roll inserts (never silent insert).",
        "async_preferred": False,
        "mutates_media": False,
        "compat_tools": ("video_propose_broll",),
        "notes": "Phase-2 proposals anchor to time_range only.",
    },
    "repurpose": {
        "summary": "Long-form → short-form package via durable repurpose path.",
        "async_preferred": True,
        "mutates_media": True,
        "compat_tools": ("video_repurpose",),
    },
    "find_moments": {
        "summary": "Local semantic moment search on a project revision.",
        "async_preferred": False,
        "mutates_media": False,
        "compat_tools": ("video_find_moments",),
    },
    "translate_captions": {
        "summary": "Translate caption files with honest language-coverage reporting.",
        "async_preferred": False,
        "mutates_media": False,
        "compat_tools": ("video_translate_captions",),
    },
    "review_package": {
        "summary": "Build a human review package for a project directory.",
        "async_preferred": False,
        "mutates_media": False,
        "compat_tools": ("video_review_package",),
    },
    "still_package": {
        "summary": "Still/plate package: match → grade → gate → receipts.",
        "async_preferred": False,
        "mutates_media": True,
        "compat_tools": ("still_package",),
    },
}
