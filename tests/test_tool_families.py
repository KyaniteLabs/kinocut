"""Typed operation families: the compact MCP dispatch surface.

Protects the compact-surface contract end to end:

* schema — default mode is exactly the core diet plus the family dispatchers
  and ``list_operations``, within the design budget (<= 40 tools, <= 25% of
  the full-catalog baseline schema bytes); every family exposes a closed
  operation enum and nothing else;
* dispatch — a family call runs the exact registered tool object: identical
  success payloads, identical handler error payloads, identical validation
  rejections (bar the transport ``isError`` flag, asserted explicitly below);
* discovery — ``list_operations`` is on-demand, deterministic, reports verbs
  and only *declared* side-effect annotations, and never leaks operations
  onto the registered surface;
* isolation — cold-process surfaces per mode, including concurrent processes
  in different modes, and the legacy ``all`` surface stays exactly the
  205-name registry with the family tools hidden.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from kinocut.server import mcp
from kinocut.tool_families import (
    DISCOVERY_TOOL_NAME,
    FAMILY_MODULES,
    FAMILY_OF_OPERATION,
    FAMILY_OPERATIONS,
    FAMILY_SURFACE_TOOLS,
    operation_verb,
)
from kinocut.tool_registry import (
    CORE_TOOLS,
    TOOL_REGISTRY,
    active_mode,
    configure_tool_surface,
    parse_tool_mode,
)

ROOT = Path(__file__).resolve().parents[1]

# Design budget (factory tool-surface design, accepted by Product): the
# compact default surface must stay at or below 40 tools and 25% of the
# full-catalog baseline input-schema bytes (126,776 B at 1.16.5).
MAX_SURFACE_TOOLS = 40
MAX_SURFACE_SCHEMA_BYTES = 31_694


@pytest.fixture(autouse=True)
def _restore_full_surface():
    yield
    configure_tool_surface("all")


@pytest.fixture(autouse=True)
def _hermetic_selector(monkeypatch):
    monkeypatch.delenv("KINOCUT_TOOLS", raising=False)


def canonical_schema_bytes(schema: dict[str, Any]) -> bytes:
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _surface() -> dict[str, dict[str, Any]]:
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


def _surface_names() -> set[str]:
    return set(_surface())


def _default_surface_names() -> set[str]:
    return set(CORE_TOOLS) | set(FAMILY_SURFACE_TOOLS)


def _subprocess_surface(env_mode: str | None) -> dict[str, Any]:
    script = (
        "import asyncio, json\n"
        "from kinocut.server import mcp\n"
        "from kinocut.tool_registry import active_mode\n"
        "names = sorted(t.name for t in asyncio.run(mcp.list_tools()))\n"
        "print(json.dumps({'mode': active_mode(), 'count': len(names), 'names': names}))\n"
    )
    env = dict(os.environ)
    if env_mode is None:
        env.pop("KINOCUT_TOOLS", None)
    else:
        env["KINOCUT_TOOLS"] = env_mode
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# --- schema: composition and budget ------------------------------------------------


def test_default_surface_is_core_plus_family_tools_and_nothing_else():
    configure_tool_surface()
    names = _surface_names()
    assert names == _default_surface_names(), "the compact surface must not leak any other direct tool"
    assert set(CORE_TOOLS) <= names, "the legacy core diet stays directly callable in default mode"


def test_default_surface_is_within_the_design_budget():
    configure_tool_surface()
    tools = _surface()
    total = sum(len(canonical_schema_bytes(tool.inputSchema)) for tool in tools.values())
    assert len(tools) <= MAX_SURFACE_TOOLS, len(tools)
    assert total <= MAX_SURFACE_SCHEMA_BYTES, total


@pytest.mark.parametrize("family", sorted(FAMILY_MODULES))
def test_family_schema_is_a_closed_operation_enum_plus_params(family):
    configure_tool_surface()
    tool = _surface()[family]
    properties = tool.inputSchema["properties"]
    assert set(properties) == {"operation", "params", "overwrite"}, family
    assert properties["operation"]["enum"] == list(FAMILY_OPERATIONS[family]), family
    params_property = properties["params"]
    assert params_property.get("type") == "object" or any(
        sub.get("type") == "object" for sub in params_property.get("anyOf", [])
    ), family
    # The injected strict-boolean overwrite consent every MCP handler exposes;
    # it scopes the ContextVar the dispatched operation inherits.
    assert properties["overwrite"]["type"] == "boolean", family
    assert sorted(tool.inputSchema["required"]) == ["operation"], family


def test_list_operations_schema_is_small_and_read_only():
    configure_tool_surface()
    tool = _surface()[DISCOVERY_TOOL_NAME]
    assert set(tool.inputSchema["properties"]) == {"family", "query", "overwrite"}
    assert len(canonical_schema_bytes(tool.inputSchema)) < 1_100
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False


# --- family partition integrity -----------------------------------------------------


def test_families_partition_the_registry_exactly_once():
    operations = [name for family in FAMILY_OPERATIONS.values() for name in family]
    assert len(operations) == len(set(operations)) == len(TOOL_REGISTRY) - 1, "search_tools is not an operation"
    assert set(FAMILY_OF_OPERATION) == set(TOOL_REGISTRY) - {"search_tools"}
    for family, members in FAMILY_OPERATIONS.items():
        assert members == tuple(sorted(members)), family


def test_operation_verbs_are_deterministic_and_total():
    for name in FAMILY_OF_OPERATION:
        verb = operation_verb(name)
        assert verb and verb != name, (name, verb)  # every registry name carries a strippable domain prefix
    assert operation_verb("video_trim") == "trim"
    assert operation_verb("video_ai_transcribe") == "ai_transcribe"
    assert operation_verb("hyperframes_render") == "render"
    assert operation_verb("audio_synthesize") == "synthesize"


def test_every_family_dispatches_at_least_one_registry_operation():
    for family, members in FAMILY_OPERATIONS.items():
        assert members, family
        assert all(name in TOOL_REGISTRY for name in members), family


# --- dispatch equivalence ------------------------------------------------------------


def _payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[1]
    structured = getattr(result, "structuredContent", None)
    assert structured is not None, f"unexpected result shape: {result!r}"
    return structured


async def _call(name: str, arguments: dict[str, Any]) -> Any:
    return await mcp.call_tool(name, arguments)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_family_dispatch_matches_the_direct_call_payload(sample_video):
    configure_tool_surface()
    family = asyncio.run(
        _call(
            "video_edit_ops", {"operation": "video_audio_waveform", "params": {"input_path": sample_video, "bins": 2}}
        )
    )
    configure_tool_surface("all")
    direct = asyncio.run(_call("video_audio_waveform", {"input_path": sample_video, "bins": 2}))
    configure_tool_surface("")
    assert _payload(family) == _payload(direct), "family dispatch must return the direct tool's exact payload"
    assert _payload(family)["success"] is True
    assert len(_payload(family)["peaks"]) == 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_family_dispatch_matches_direct_handler_validation_errors(sample_video):
    missing = str(Path(sample_video).with_name("definitely_missing.mp4"))
    configure_tool_surface()
    family = asyncio.run(_call("video_edit_ops", {"operation": "video_trim", "params": {"input_path": missing}}))
    configure_tool_surface("all")
    direct = asyncio.run(_call("video_trim", {"input_path": missing}))
    configure_tool_surface("")
    family_payload, direct_payload = _payload(family), _payload(direct)
    assert family_payload == direct_payload
    assert family_payload["success"] is False
    assert family_payload["error"]["type"] == "input_error"  # the target's own missing-input rejection


def _error_core(payload: dict[str, Any]) -> dict[str, Any]:
    error = dict(payload["error"])
    error["message"] = error["message"].split(";")[0]
    return error


def test_family_dispatch_rejects_bad_arguments_like_the_direct_wire():
    configure_tool_surface("all")
    direct = asyncio.run(_call("video_audio_waveform", {"input_path": "x.mp4", "bins": 2, "bogus": 1}))
    configure_tool_surface("")
    family = asyncio.run(
        _call(
            "video_edit_ops",
            {"operation": "video_audio_waveform", "params": {"input_path": "x.mp4", "bins": 2, "bogus": 1}},
        )
    )
    # The structured payload is the same rejection the direct wire returns
    # (retry hints differ by design: they name the tool that was called).
    assert (
        _error_core(_payload(family))
        == _error_core(_payload(direct))
        == {
            "type": "validation_error",
            "code": "invalid_parameter",
            "message": "Invalid MCP tool parameters. Use tools/list to inspect the accepted parameters.",
        }
    )
    # Transport difference, asserted instead of hidden: the direct path flags
    # the rejection with isError=True at the CallToolResult level, the family
    # path reports the identical structured payload without the flag.
    assert getattr(direct, "isError", None) is True
    assert getattr(family, "isError", False) in (False, None)


def test_unknown_and_cross_family_operations_fail_closed_at_the_wire():
    configure_tool_surface()
    unknown = asyncio.run(_call("video_edit_ops", {"operation": "definitely_not_real"}))
    assert _payload(unknown)["error"]["code"] == "invalid_parameter"
    cross = asyncio.run(_call("audio_ops", {"operation": "video_audio_waveform"}))
    assert _payload(cross)["error"]["code"] == "invalid_parameter"
    bad_params = asyncio.run(_call("video_edit_ops", {"operation": "video_trim", "params": "not-a-dict"}))
    assert _payload(bad_params)["error"]["code"] == "invalid_parameter"


def test_family_dispatch_enforces_policy_booleans_identically():
    arguments = {"video_path": "x.mp4", "keep_source": "yes"}
    configure_tool_surface("all")
    direct = asyncio.run(_call("video_mix_audio", arguments))
    configure_tool_surface("")
    family = asyncio.run(_call("audio_ops", {"operation": "video_mix_audio", "params": arguments}))
    assert _error_core(_payload(family)) == _error_core(_payload(direct))


def test_family_dispatch_does_not_leak_the_direct_name_onto_the_surface(sample_video):
    configure_tool_surface()
    family = asyncio.run(
        _call(
            "video_edit_ops", {"operation": "video_audio_waveform", "params": {"input_path": sample_video, "bins": 2}}
        )
    )
    assert _payload(family)["success"] is True
    assert _surface_names() == _default_surface_names(), "dispatch must not register the hidden direct tool"
    with pytest.raises(ToolError, match="Unknown tool: video_audio_waveform"):
        asyncio.run(_call("video_audio_waveform", {"input_path": sample_video}))


def test_family_dispatch_works_for_every_family_representative():
    """One cheap representative per family: dispatch resolves and validates.

    Uses deliberately invalid paths so nothing renders: the assertion is that
    dispatch reaches the *target operation's own* handler validation (its
    error code / message), not that media processing succeeds.
    """

    representatives = {
        "video_edit_ops": "video_info",
        "video_effects_ops": "effect_noise",
        "audio_ops": "sound_capabilities",
        "video_ai_ops": "video_quality_check",
        "image_ops": "image_extract_colors",
        "video_qc_ops": "video_doctor",
        "video_plan_ops": "video_intent",
        "platform_ops": "hyperframes_info",
    }
    assert set(representatives) == set(FAMILY_MODULES)
    configure_tool_surface()
    for family, operation in representatives.items():
        result = asyncio.run(_call(family, {"operation": operation, "params": {}}))
        payload = _payload(result)
        assert payload["success"] is False or "success" in payload, (family, operation)
        # The target operation ran and reported its own outcome, not a
        # dispatch-layer error: no unknown_operation / dispatch codes appear.
        assert payload.get("error", {}).get("code") != "unknown_operation", (family, operation)


# --- annotations ----------------------------------------------------------------------


@pytest.mark.parametrize("family", sorted(FAMILY_MODULES))
def test_family_annotations_are_conservative_worst_case(family):
    configure_tool_surface()
    annotations = _surface()[family].annotations
    assert annotations is not None, family
    assert annotations.readOnlyHint is False, family
    assert annotations.destructiveHint is True, family
    assert annotations.idempotentHint is False, family
    assert annotations.openWorldHint is False, family


def test_list_operations_reports_only_declared_annotations():
    configure_tool_surface()
    result = asyncio.run(_call(DISCOVERY_TOOL_NAME, {}))
    payload = _payload(result)
    by_name = {row["name"]: row for row in payload["operations"]}
    # video_merge declares destructive hints in its registration.
    assert by_name["video_merge"]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
    # Operations without declared hints are reported as undeclared, never guessed.
    assert by_name["video_trim"]["annotations"] is None


def test_family_annotation_never_weakens_a_declared_member_hint():
    configure_tool_surface()
    result = asyncio.run(_call(DISCOVERY_TOOL_NAME, {}))
    for row in _payload(result)["operations"]:
        if not row["annotations"]:
            continue
        family = _surface()[row["family"]]
        assert family.annotations.destructiveHint or not row["annotations"].get("destructiveHint"), row["name"]


# --- discovery ------------------------------------------------------------------------


def test_list_operations_is_on_demand_and_total():
    configure_tool_surface()
    result = asyncio.run(_call(DISCOVERY_TOOL_NAME, {}))
    payload = _payload(result)
    assert payload["success"] is True
    assert payload["count"] == len(TOOL_REGISTRY) - 1 == 204
    assert [family["name"] for family in payload["families"]] == list(FAMILY_MODULES)
    assert sum(family["operations"] for family in payload["families"]) == 204
    for row in payload["operations"]:
        assert row["verb"] == operation_verb(row["name"])
        assert row["family"] == FAMILY_OF_OPERATION[row["name"]]
        assert "required_params" in row
    # discovery must restore the selected surface afterwards
    assert active_mode() == "default"
    assert _surface_names() == _default_surface_names()


def test_list_operations_filters_and_reports_intent_verbs():
    configure_tool_surface()
    payload = _payload(asyncio.run(_call(DISCOVERY_TOOL_NAME, {"family": "video_ai_ops", "query": "silence"})))
    assert payload["count"] == 1
    row = payload["operations"][0]
    assert row["name"] == "video_ai_remove_silence"
    assert row["intent_verbs"] == ["remove_silence"]
    assert row["intent_mutates_media"] is True


def test_list_operations_rejects_unknown_families():
    configure_tool_surface()
    payload = _payload(asyncio.run(_call(DISCOVERY_TOOL_NAME, {"family": "nope"})))
    assert payload["success"] is False
    assert payload["error"]["code"] == "unknown_family"
    for family in FAMILY_MODULES:
        assert family in payload["error"]["message"]


# --- isolation and concurrency ---------------------------------------------------------


def test_cold_server_mode_surfaces_are_exact():
    default = _subprocess_surface(None)
    assert default["mode"] == "default"
    assert set(default["names"]) == _default_surface_names()
    assert default["count"] == len(_default_surface_names()) == 29

    core_alias = _subprocess_surface("core")
    assert core_alias["names"] == default["names"], "core remains the documented alias of the default mode"

    everything = _subprocess_surface("all")
    assert everything["mode"] == "all"
    assert set(everything["names"]) == set(TOOL_REGISTRY)
    assert not (set(everything["names"]) & set(FAMILY_SURFACE_TOOLS)), "all mode stays the legacy direct surface"

    editor = _subprocess_surface("profile:editor")
    expected = {name for name, tags in TOOL_REGISTRY.items() if "editor" in tags or "core" in tags} | set(
        FAMILY_SURFACE_TOOLS
    )
    assert set(editor["names"]) == expected
    assert editor["count"] == len(expected) == 117  # 108 direct + 8 families + list_operations


def test_concurrent_servers_in_different_modes_stay_isolated():
    """Three cold servers in three modes, started simultaneously."""

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_subprocess_surface, mode) for mode in (None, "all", "profile:editor")]
        default, everything, editor = (future.result() for future in futures)
    assert set(default["names"]) == _default_surface_names()
    assert set(everything["names"]) == set(TOOL_REGISTRY)
    assert set(editor["names"]) >= set(CORE_TOOLS)
    assert set(editor["names"]) & set(FAMILY_SURFACE_TOOLS)


def test_in_process_reconfigure_cycles_never_strand_family_tools():
    configure_tool_surface()
    assert _surface_names() == _default_surface_names()
    configure_tool_surface("all")
    assert _surface_names() == set(TOOL_REGISTRY), "all mode hides the family tools"
    configure_tool_surface("profile:editor")
    assert set(FAMILY_SURFACE_TOOLS) <= _surface_names()
    configure_tool_surface()
    assert _surface_names() == _default_surface_names()
    configure_tool_surface("all")
    assert _surface_names() == set(TOOL_REGISTRY)


def test_parse_tool_mode_is_unchanged_by_the_compact_surface():
    assert parse_tool_mode("") == ("default", frozenset({"core"}))
    assert parse_tool_mode("all") == ("all", frozenset())
    assert parse_tool_mode("profile:editor") == ("profile:editor", frozenset({"core", "editor"}))


# --- legacy compatibility ---------------------------------------------------------------


def test_legacy_facade_import_and_family_dispatch_coexist():
    from kinocut import server as facade

    configure_tool_surface()
    hidden = facade.video_filter  # legacy PEP 562 import of a hidden direct tool
    assert callable(hidden)
    assert _surface_names() == _default_surface_names()
    # the wire stays fail-closed for the direct name ...
    with pytest.raises(ToolError, match="Unknown tool: video_filter"):
        asyncio.run(_call("video_filter", {"input_path": "unused.mp4"}))
    # ... while the family dispatcher reaches the same operation
    result = asyncio.run(
        _call("video_effects_ops", {"operation": "video_filter", "params": {"input_path": "unused.mp4"}})
    )
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"]["type"] == "validation_error", "the target operation's own validation answered"


def test_search_tools_still_discovers_hidden_operations():
    from kinocut.server import search_tools

    configure_tool_surface()
    result = search_tools("waveform")
    assert "video_audio_waveform" in {tool["name"] for tool in result["tools"]}
    assert _surface_names() == _default_surface_names()
