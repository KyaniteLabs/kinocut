"""Typed operation families: the compact MCP dispatch surface.

The registry owns 205 direct tool registrations (``KINOCUT_TOOLS=all``).  This
module partitions those operations into a small set of *families* so the
default and profile surfaces can expose every operation through a handful of
typed dispatch tools instead of one schema per operation.

Design rules:

* Families are declared over *modules*, never over individual names, so the
  partition cannot drift from ``tool_registry``: every registry name except
  ``search_tools`` belongs to exactly one family (guarded by tests).
* The dispatch tools are typed wrappers, not a lossy escape hatch: the
  ``operation`` argument is a closed enum of family members and ``params`` is
  validated against the target operation's own FastMCP argument contract
  before the operation runs — identical validation, identical results,
  identical error payloads to the direct tool call.
* Side-effect semantics are never weakened: family tools carry conservative
  worst-case MCP annotations, and per-operation hints are reported honestly
  (only what the operation's registration actually declares, plus the intent
  verb table's ``mutates_media`` where a verb routes to the operation).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Family tool name -> registry modules whose operations it dispatches.
# ``search_tools`` is discovery infrastructure, not an operation, and stays a
# direct core tool; it is deliberately absent from every family.
FAMILY_MODULES: Mapping[str, tuple[str, ...]] = {
    "video_edit_ops": (
        "server_tools_basic",
        "server_tools_advanced",
        "server_tools_media",
    ),
    "video_effects_ops": (
        "server_tools_effects",
        "server_tools_glitch",
        "server_tools_glitch_shader",
    ),
    "audio_ops": ("server_tools_audio", "server_tools_sound"),
    "video_ai_ops": ("server_tools_ai", "server_tools_aivideo"),
    "image_ops": ("server_tools_image",),
    "video_qc_ops": (
        "server_tools_inspection",
        "server_tools_doctor",
        "server_tools_guardrails",
        "server_tools_motion_acceptance",
        "server_tools_release",
    ),
    "video_plan_ops": (
        "server_tools_intent",
        "server_tools_creation",
        "server_tools_postrescue",
        "server_tools_repurpose",
        "server_tools_rescue",
        "server_tools_workflow",
    ),
    "platform_ops": ("server_tools_hyperframes", "server_tools_revideo", "server_tools_shorts"),
}

FAMILY_TITLES: Mapping[str, str] = {
    "video_edit_ops": "Edit operations (trim, merge, text, convert, export, metadata, batch)",
    "video_effects_ops": "Effect operations (filters, transitions, glitch, motion graphics)",
    "audio_ops": "Audio operations (mix, synthesize, presets, sound pipeline, QC)",
    "video_ai_ops": "AI operations (transcription, scene detect, upscale, verdicts, quality)",
    "image_ops": "Image and still operations (colors, palettes, grade, gate, packaging)",
    "video_qc_ops": "Inspection and release operations (doctor, preflight, guardrails, review, publish)",
    "video_plan_ops": "Planning operations (intent, cutfiles, timelines, rescue, workflow, repurpose)",
    "platform_ops": "Platform operations (hyperframes, revideo, shorts packaging)",
}

# One-line usage summaries embedded in each family tool schema.  Kept short on
# purpose: schemas are the budget this surface exists to shrink.
FAMILY_SUMMARIES: Mapping[str, str] = {
    "video_edit_ops": (
        "Run one edit operation. operation is one of this family's names (see list_operations); "
        "params holds that operation's exact arguments."
    ),
    "video_effects_ops": (
        "Run one effect operation. operation is one of this family's names (see list_operations); "
        "params holds that operation's exact arguments."
    ),
    "audio_ops": (
        "Run one audio operation. operation is one of this family's names (see list_operations); "
        "params holds that operation's exact arguments."
    ),
    "video_ai_ops": (
        "Run one AI operation. operation is one of this family's names (see list_operations); "
        "params holds that operation's exact arguments."
    ),
    "image_ops": (
        "Run one image/still operation. operation is one of this family's names (see list_operations); "
        "params holds that operation's exact arguments."
    ),
    "video_qc_ops": (
        "Run one inspection/release operation. operation is one of this family's names (see list_operations); "
        "params holds that operation's exact arguments."
    ),
    "video_plan_ops": (
        "Run one planning operation. operation is one of this family's names (see list_operations); "
        "params holds that operation's exact arguments."
    ),
    "platform_ops": (
        "Run one platform operation. operation is one of this family's names (see list_operations); "
        "params holds that operation's exact arguments."
    ),
}

# The on-demand discovery tool that lists families, operations, verbs and
# per-operation annotations. Lives beside the families on the compact surface.
DISCOVERY_TOOL_NAME = "list_operations"

# Domain prefixes stripped when deriving an operation's verb token. The verb is
# the action the operation name itself carries — deterministic, never curated
# by hand, and stable across catalog growth.
_VERB_PREFIXES = (
    "video_",
    "audio_",
    "effect_",
    "glitch_",
    "transition_",
    "hyperframes_",
    "image_",
    "still_",
    "sound_",
    "revideo_",
    "shorts_",
    "style_",
    "storyboard_",
    "shot_",
)


def operation_verb(operation: str) -> str:
    """Return the operation's verb token (registry name minus domain prefix)."""

    for prefix in _VERB_PREFIXES:
        if operation.startswith(prefix) and len(operation) > len(prefix):
            return operation[len(prefix) :]
    return operation


def intent_verbs_for_operation(operation: str) -> tuple[str, ...]:
    """Canonical ``video_intent`` verbs whose compat route includes operation."""

    from .intent.verbs import INTENT_VERBS

    return tuple(sorted(verb for verb, meta in INTENT_VERBS.items() if operation in meta.get("compat_tools", ())))


def operation_side_effects(operation: str) -> dict[str, Any]:
    """Report only side-effect facts that are actually declared somewhere.

    Sources: the operation's own MCP registration annotations (read live by
    the discovery tool once the module is loaded — never guessed here) and the
    intent verb table's ``mutates_media`` flags. Undeclared stays ``None``;
    this function never invents a hint.
    """

    from .intent.verbs import INTENT_VERBS

    mutates = [
        meta.get("mutates_media") for verb, meta in INTENT_VERBS.items() if operation in meta.get("compat_tools", ())
    ]
    declared_mutating = [flag for flag in mutates if flag is True]
    return {
        "intent_mutates_media": bool(declared_mutating) if declared_mutating else None,
        "intent_verbs": intent_verbs_for_operation(operation),
    }


def _build() -> tuple[dict[str, tuple[str, ...]], dict[str, str], frozenset[str]]:
    from .tool_registry import TOOL_NAMES_BY_MODULE

    operations: dict[str, tuple[str, ...]] = {}
    owner: dict[str, str] = {}
    for family, modules in FAMILY_MODULES.items():
        names: list[str] = []
        for module in modules:
            for name in TOOL_NAMES_BY_MODULE[module]:
                if name == "search_tools":
                    continue
                if name in owner:
                    raise RuntimeError(f"tool {name} claimed by families {owner[name]} and {family}")
                owner[name] = family
                names.append(name)
        operations[family] = tuple(sorted(names))
    missing = set(owner) ^ {name for names in TOOL_NAMES_BY_MODULE.values() for name in names if name != "search_tools"}
    if missing:
        raise RuntimeError(f"family partition does not cover the registry exactly: {sorted(missing)}")
    return operations, owner, frozenset((*FAMILY_MODULES, DISCOVERY_TOOL_NAME))


# Family tool name -> sorted member operation names.
FAMILY_OPERATIONS: Mapping[str, tuple[str, ...]]
# Operation name -> family tool that dispatches it.
FAMILY_OF_OPERATION: Mapping[str, str]
# Every tool name the compact surface registers (family dispatchers + discovery).
FAMILY_SURFACE_TOOLS: frozenset[str]
FAMILY_OPERATIONS, FAMILY_OF_OPERATION, FAMILY_SURFACE_TOOLS = _build()
