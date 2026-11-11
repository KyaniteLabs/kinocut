"""Typed operation families: the compact MCP dispatch surface.

Protects the compact-surface contract end to end:

* schema — default mode is exactly the core diet plus the family dispatchers,
  ``list_operations`` and ``describe_operation``, within the design budget
  (<= 40 tools, <= 25% of the full-catalog baseline schema bytes); every
  family exposes a closed operation enum and nothing else;
* dispatch — a family call runs the exact registered tool object: identical
  success payloads, identical handler error cores (bar the transport
  ``isError`` flag and the retargeted retry hint, both asserted explicitly
  below), identical validation rejections; family-level ``overwrite`` consent
  reaches the operation unless ``params`` carries an explicit override;
* annotations — open-world hints follow the audited ``FAMILY_OPEN_WORLD``
  table and are backed by behavior: network-capable members are demonstrably
  reachable through the open families — including the configuration-gated
  remote vision provider reached via ``video_plan_ops`` (off makes zero
  attempts, explicit remote config makes exactly one, intercepted at the
  provider boundary) and the diagnostic package launcher reached via
  ``video_qc_ops`` (no hyperframes on PATH and no configured command makes
  zero launcher calls; either supported configuration makes exactly one
  ``npx --yes hyperframes --version``, intercepted at the final subprocess
  boundary) — and URL inputs are rejected by the closed ones;
* discovery — ``list_operations`` is on-demand, deterministic, reports verbs
  and only *declared* side-effect annotations, and never leaks operations
  onto the registered surface; ``describe_operation`` returns the hidden
  operation's complete inputSchema — byte-for-byte the direct tool's — with
  explicit family callability and only CLI routes that really exist;
* isolation — cold-process surfaces per mode, including concurrent processes
  in different modes, and the legacy ``all`` surface stays exactly the
  205-name registry with the family tools hidden.
"""

from __future__ import annotations

import argparse
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
    DESCRIBE_TOOL_NAME,
    DISCOVERY_TOOL_NAME,
    FAMILY_MODULES,
    FAMILY_OF_OPERATION,
    FAMILY_OPEN_WORLD,
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
    assert set(tool.inputSchema["properties"]) == {"family", "query"}
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
    assert family_payload["success"] is False
    assert _error_core(family_payload) == _error_core(direct_payload)
    assert family_payload["error"]["type"] == "input_error"  # the target's own missing-input rejection
    # R4: the retry hint is retargeted at the family surface — the message
    # core is the direct tool's, the invocation names the family dispatcher.
    assert family_payload["error"]["message"].startswith(direct_payload["error"]["message"].split(";")[0])
    assert 'call video_edit_ops(operation="video_trim", params={...})' in family_payload["error"]["message"]
    assert "call video_trim " not in family_payload["error"]["message"]


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
    # The structured rejection core is the same the direct wire returns; the
    # guidance differs by design (R4): family dispatch names the selected
    # operation and points at describe_operation instead of tools/list, which
    # cannot show a hidden operation's schema.
    assert _error_core(_payload(family))["type"] == _error_core(_payload(direct))["type"] == "validation_error"
    assert _error_core(_payload(family))["code"] == _error_core(_payload(direct))["code"] == "invalid_parameter"
    family_message = _payload(family)["error"]["message"]
    assert (
        "Invalid MCP tool parameters for operation 'video_audio_waveform'. "
        "Use describe_operation to inspect its accepted parameters." in family_message
    )
    # The full emitted hint — asserted, not stripped: usable MCP context plus a
    # CLI route that really exists (audio-waveform is a kino subcommand).
    assert (
        '; retry with call video_edit_ops(operation="video_audio_waveform", params={...}) '
        "with corrected parameters (MCP) / run kino audio-waveform with corrected flags (CLI)" in family_message
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
    assert _error_core(_payload(family))["type"] == _error_core(_payload(direct))["type"]
    assert _error_core(_payload(family))["code"] == _error_core(_payload(direct))["code"]
    assert (
        "Invalid MCP tool parameters for operation 'video_mix_audio'. "
        "Use describe_operation to inspect its accepted parameters." in _payload(family)["error"]["message"]
    ), "the shared wire-path policy rejection answered under the family surface"


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


# --- overwrite consent (R2) --------------------------------------------------------------


def _seed_output(sample_video: str, name: str) -> tuple[str, bytes, bytes]:
    out = Path(sample_video).with_name(name)
    shutil.copyfile(sample_video, out)
    before = out.read_bytes()
    return str(out), before, Path(sample_video).read_bytes()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_family_overwrite_consent_matrix(sample_video):
    """The Security round-1 control table, as a regression test."""

    configure_tool_surface()
    trim = {"input_path": sample_video, "start": 0.0, "end": 1.0}

    # outer consent reaches the operation when inner overwrite is omitted
    out, before, _ = _seed_output(sample_video, "consent_outer_true.mp4")
    payload = _payload(
        asyncio.run(
            _call(
                "video_edit_ops", {"operation": "video_trim", "overwrite": True, "params": {**trim, "output_path": out}}
            )
        )
    )
    assert payload["success"] is True, payload
    assert Path(out).read_bytes() != before, "family-level consent must let the render replace existing media"

    # explicit params.overwrite=true also works
    out, before, _ = _seed_output(sample_video, "consent_inner_true.mp4")
    payload = _payload(
        asyncio.run(
            _call(
                "video_edit_ops", {"operation": "video_trim", "params": {**trim, "output_path": out, "overwrite": True}}
            )
        )
    )
    assert payload["success"] is True, payload
    assert Path(out).read_bytes() != before

    # explicit inner false overrides outer true (consent is never implied)
    out, before, _ = _seed_output(sample_video, "consent_inner_false.mp4")
    payload = _payload(
        asyncio.run(
            _call(
                "video_edit_ops",
                {
                    "operation": "video_trim",
                    "overwrite": True,
                    "params": {**trim, "output_path": out, "overwrite": False},
                },
            )
        )
    )
    assert payload["success"] is False
    assert payload["error"]["code"] == "output_exists"
    assert Path(out).read_bytes() == before

    # no consent anywhere: existing output is preserved
    out, before, _ = _seed_output(sample_video, "consent_default.mp4")
    payload = _payload(
        asyncio.run(_call("video_edit_ops", {"operation": "video_trim", "params": {**trim, "output_path": out}}))
    )
    assert payload["success"] is False
    assert payload["error"]["code"] == "output_exists"
    assert Path(out).read_bytes() == before

    # non-media files stay protected even with explicit outer consent
    protected = Path(sample_video).with_name("protected.txt")
    protected.write_text("operator asset")
    payload = _payload(
        asyncio.run(
            _call(
                "video_edit_ops",
                {"operation": "video_trim", "overwrite": True, "params": {**trim, "output_path": str(protected)}},
            )
        )
    )
    assert payload["success"] is False
    assert protected.read_text() == "operator asset"

    # strict booleans: a string consent is rejected at the schema
    payload = _payload(
        asyncio.run(_call("video_edit_ops", {"operation": "video_trim", "overwrite": "true", "params": trim}))
    )
    assert payload["error"]["code"] == "invalid_parameter"

    # consent does not leak into a subsequent call
    out, before, _ = _seed_output(sample_video, "consent_after.mp4")
    payload = _payload(
        asyncio.run(_call("video_edit_ops", {"operation": "video_trim", "params": {**trim, "output_path": out}}))
    )
    assert payload["error"]["code"] == "output_exists"
    assert Path(out).read_bytes() == before


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_direct_overwrite_behavior_is_unchanged(sample_video):
    configure_tool_surface("all")
    out, before, _ = _seed_output(sample_video, "direct_overwrite.mp4")
    payload = _payload(
        asyncio.run(
            _call(
                "video_trim",
                {"input_path": sample_video, "start": 0.0, "end": 1.0, "output_path": out, "overwrite": True},
            )
        )
    )
    assert payload["success"] is True, payload
    assert Path(out).read_bytes() != before


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_concurrent_family_calls_isolate_their_own_consent(sample_video):
    """Two interleaved family calls: consenting and non-consenting renders
    must not bleed consent into each other."""

    configure_tool_surface()
    out_a, before_a, _ = _seed_output(sample_video, "concurrent_a.mp4")
    out_b, before_b, _ = _seed_output(sample_video, "concurrent_b.mp4")
    trim = {"input_path": sample_video, "start": 0.0, "end": 1.0}

    async def scenario():
        consenting = _call(
            "video_edit_ops", {"operation": "video_trim", "overwrite": True, "params": {**trim, "output_path": out_a}}
        )
        refusing = _call("video_edit_ops", {"operation": "video_trim", "params": {**trim, "output_path": out_b}})
        return await asyncio.gather(consenting, refusing)

    results = asyncio.run(scenario())
    assert _payload(results[0])["success"] is True
    assert _payload(results[1])["success"] is False
    assert _payload(results[1])["error"]["code"] == "output_exists"
    assert Path(out_a).read_bytes() != before_a
    assert Path(out_b).read_bytes() == before_b


# --- annotations ----------------------------------------------------------------------


@pytest.mark.parametrize("family", sorted(FAMILY_MODULES))
def test_family_annotations_are_conservative_worst_case(family):
    configure_tool_surface()
    annotations = _surface()[family].annotations
    assert annotations is not None, family
    assert annotations.readOnlyHint is False, family
    assert annotations.destructiveHint is True, family
    assert annotations.idempotentHint is False, family
    # R1: open-world follows the audited table, not a blanket claim.
    assert annotations.openWorldHint is FAMILY_OPEN_WORLD[family], family


def test_open_world_verdicts_are_total_and_nonempty():
    assert set(FAMILY_OPEN_WORLD) == set(FAMILY_MODULES)
    assert any(FAMILY_OPEN_WORLD.values()), "at least the audited network-capable families are open"
    assert not all(FAMILY_OPEN_WORLD.values()), "closed claims carry evidence and stay closed"


def test_network_capable_members_are_reachable_through_open_families(monkeypatch, tmp_path):
    """Behavior evidence for every open-world verdict — intercepted, no network.

    Each probe drives a network-capable member through its family dispatcher
    far enough to observe the capability engage (the engine entry point is
    monkeypatched to capture its arguments), while the family tool advertises
    openWorldHint=true on tools/list.
    """

    configure_tool_surface()
    captured: dict[str, Any] = {}
    # 1x1 transparent PNG — a real local file the input validation accepts.
    frame = tmp_path / "frame.png"
    frame.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6260010000000500010d0a2db40000000049454e44ae426082"
        )
    )

    def fake_analyze(input_path, **kwargs):  # ai_engine.analyze_video — URL sources
        captured["video_analyze"] = input_path
        return {"success": True}

    def fake_capture(url, **kwargs):  # hyperframes_engine.capture — website download
        captured["hyperframes_capture"] = url
        return {"ok": True}

    def fake_analyze_product(image_path, use_ai=False, **kwargs):  # vision endpoint
        captured["image_analyze_product"] = use_ai
        return {"image_path": image_path, "colors": [], "description": None, "ai_description": use_ai}

    import kinocut.ai_engine as ai_engine
    import kinocut.hyperframes_engine as hyperframes_engine
    import kinocut.image_engine as image_engine

    monkeypatch.setattr(ai_engine, "analyze_video", fake_analyze, raising=False)
    monkeypatch.setattr(hyperframes_engine, "capture", fake_capture, raising=False)
    monkeypatch.setattr(image_engine, "analyze_product", fake_analyze_product, raising=False)

    surface = _surface()
    assert surface["video_ai_ops"].annotations.openWorldHint is True
    result = asyncio.run(
        _call(
            "video_ai_ops",
            {"operation": "video_analyze", "params": {"input_path": "https://example.invalid/probe.mp4"}},
        )
    )
    assert _payload(result)["success"] is True
    assert captured["video_analyze"] == "https://example.invalid/probe.mp4"

    assert surface["platform_ops"].annotations.openWorldHint is True
    result = asyncio.run(
        _call("platform_ops", {"operation": "hyperframes_capture", "params": {"url": "https://example.invalid/page"}})
    )
    assert _payload(result)["success"] is True
    assert captured["hyperframes_capture"] == "https://example.invalid/page"

    assert surface["image_ops"].annotations.openWorldHint is True
    result = asyncio.run(
        _call(
            "image_ops",
            {"operation": "image_analyze_product", "params": {"image_path": str(frame), "use_ai": True}},
        )
    )
    assert _payload(result)["success"] is True
    assert captured["image_analyze_product"] is True


@pytest.mark.parametrize(
    ("family", "operation"),
    [
        ("video_edit_ops", "video_add_text"),
        ("video_effects_ops", "effect_chromatic_aberration"),
        ("audio_ops", "audio_effects"),
    ],
)
def test_closed_families_reject_url_inputs_before_any_network(family, operation):
    """Behavior evidence for every closed-world verdict: a URL input is
    rejected by local path validation — the closed families have no
    URL-accepting input path, so nothing can be fetched through them.

    The remaining closed verdicts also hold under *configuration* audits:
    no env-gated provider route or package-launcher argv exists in their
    members (see the per-family evidence in ``kinocut/tool_families.py``,
    the provider-boundary test below, and the doctor launcher-boundary
    test for the family that does carry one)."""

    configure_tool_surface()
    assert _surface()[family].annotations.openWorldHint is False
    result = asyncio.run(
        _call(family, {"operation": operation, "params": {"input_path": "https://example.invalid/x.mp4"}})
    )
    payload = _payload(result)
    assert payload["success"] is False
    error = payload["error"]
    # The URL is rejected by local path validation (contract model or handler)
    # — before any engine or fetch could run.
    assert error["type"] in {"validation_error", "input_error"}, (family, error)
    assert error["code"] in {"invalid_parameter", "invalid_input", "input_error", "unsafe_path"}, (family, error)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_vision_provider_boundary_off_vs_remote_through_video_plan_ops(monkeypatch, sample_video):
    """Security round 2 R1: ``video_plan_ops`` is open-world because its member
    ``video_qc_vision`` reaches the remote vision provider.

    The provider boundary (``vision_provider.assess_keyframes``) is
    intercepted, so no request leaves the process. With the vision mode
    unset/off — the shipped default — a family dispatch of ``video_qc_vision``
    over a real local video makes ZERO provider attempts; under the supported
    explicit remote configuration it makes EXACTLY ONE, carrying the really
    extracted keyframe files, while the family advertises
    ``openWorldHint=true``.
    """

    configure_tool_surface()
    from kinocut.watching import vision_provider
    from kinocut.watching.vision_provider import SemanticVisionAssessment

    attempts: list[tuple[str, list[dict]]] = []

    def fake_assess(model, samples):
        attempts.append((model, samples))
        return SemanticVisionAssessment(verdict="pass", summary="provider boundary intercepted", findings=())

    monkeypatch.setattr(vision_provider, "assess_keyframes", fake_assess)

    surface = _surface()
    assert surface["video_plan_ops"].annotations.openWorldHint is True

    def _dispatch() -> dict[str, Any]:
        result = asyncio.run(
            _call("video_plan_ops", {"operation": "video_qc_vision", "params": {"input_path": sample_video}})
        )
        payload = _payload(result)
        assert payload["success"] is True, payload
        return payload

    # 1) Default/off: zero provider attempts, assessment not evaluated.
    for var in ("KINOCUT_VISION_MODE", "KINOCUT_VISION_MODEL", "ANTHROPIC_API_KEY", "KINOCUT_VISION_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    payload = _dispatch()
    assert attempts == []
    assert payload["assessment_status"] == "not_evaluated"

    # 2) Explicit remote configuration: exactly one provider attempt whose
    #    samples are the really extracted keyframe files (fake placeholder
    #    key — the boundary is intercepted, nothing leaves the process).
    monkeypatch.setenv("KINOCUT_VISION_MODE", "remote")
    monkeypatch.setenv("KINOCUT_VISION_MODEL", "fixture-vision-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-placeholder-key")
    payload = _dispatch()
    assert len(attempts) == 1
    model, samples = attempts[0]
    assert model == "fixture-vision-model"
    assert samples, "real keyframe extraction must reach the provider boundary"
    assert all(Path(sample["path"]).is_file() for sample in samples)
    assert payload["assessment_status"] == "evaluated_sampled_frames"
    assert payload["auto_scored"] is True


def test_doctor_package_launcher_boundary_through_video_qc_ops(monkeypatch):
    """Security round 3 R1: ``video_qc_ops`` stays open-world-annotated, but
    ``video_doctor`` must never reach a package launcher.

    ``npx --yes hyperframes --version`` is not a local version query: npx may
    fetch and install a missing ``hyperframes`` package from the npm registry
    before executing it. Doctor reads versions offline instead
    (``kinocut.doctor_offline``), so whether a hyperframes CLI is on PATH or
    the ``npx --yes hyperframes`` prefix is configured in
    ``MCP_VIDEO_HYPERFRAMES_COMMAND``, no launcher call reaches the OS
    boundary. Every final ``subprocess.run`` is intercepted, so nothing
    executes or leaves the process.
    """

    import kinocut.doctor as doctor

    configure_tool_surface()
    surface = _surface()
    assert surface["video_qc_ops"].annotations.openWorldHint is True

    original_diagnostics = doctor.run_diagnostics
    seen: list[list[str]] = []

    def guard(command, **kwargs):
        seen.append(list(command))
        versions = {
            "node": "v22.0.0",
            "ffmpeg": "ffmpeg version 7.1",
            "ffprobe": "ffprobe version 7.1",
            "python3": "Python 3.12.3",
        }
        version = versions.get(command[0], "0.8.140")
        return subprocess.CompletedProcess(command, 0, stdout=version + "\n", stderr="")

    def dispatch(has_hyperframes: bool, configured_command: str) -> list[list[str]]:
        """Family-dispatch video_doctor; return every npx hyperframes call."""

        def which(name: str) -> str | None:
            if name == "hyperframes" and not has_hyperframes:
                return None
            return f"/launcher-probe/bin/{name}"

        def diagnostics(**_kwargs):
            return original_diagnostics(which=which)

        seen.clear()
        monkeypatch.delenv("MCP_VIDEO_HYPERFRAMES_COMMAND", raising=False)
        if configured_command:
            monkeypatch.setenv("MCP_VIDEO_HYPERFRAMES_COMMAND", configured_command)
        monkeypatch.setattr(doctor, "run_diagnostics", diagnostics)
        monkeypatch.setattr(subprocess, "run", guard)
        result = asyncio.run(_call("video_qc_ops", {"operation": "video_doctor"}))
        payload = _payload(result)
        assert payload["success"] is True, payload
        return [cmd for cmd in seen if cmd[:3] == ["npx", "--yes", "hyperframes"]]

    # 1) No hyperframes on PATH and no configured command: the shipped-absent
    #    control — zero package-launcher invocations reach the OS boundary.
    assert dispatch(has_hyperframes=False, configured_command="") == []

    # 2) and 3): with a hyperframes CLI on PATH, or with the explicit
    #    ``npx --yes hyperframes`` prefix configured, doctor still executes no
    #    package launcher: versions are read offline (kinocut.doctor_offline).
    assert dispatch(has_hyperframes=True, configured_command="") == []
    assert dispatch(has_hyperframes=False, configured_command="npx --yes hyperframes") == []


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
    assert by_name["video_resize"]["annotations"] is None


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
    assert payload["count"] == len(TOOL_REGISTRY) - 1 == 205
    assert [family["name"] for family in payload["families"]] == list(FAMILY_MODULES)
    assert sum(family["operations"] for family in payload["families"]) == 205
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
    # The discovery tools are MCP-only: their retry hints must not derive a
    # nonexistent kino route from the tool name.
    assert payload["error"]["message"].endswith("; retry with call list_operations with corrected parameters (MCP)")


# --- describe_operation: on-demand input contracts (R3) --------------------------------


def test_describe_operation_schema_is_small_and_read_only():
    configure_tool_surface()
    tool = _surface()[DESCRIBE_TOOL_NAME]
    assert set(tool.inputSchema["properties"]) == {"operation"}
    assert len(canonical_schema_bytes(tool.inputSchema)) < 900
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False


def test_describe_operation_returns_the_direct_tools_exact_schema():
    configure_tool_surface()
    payload = _payload(asyncio.run(_call(DESCRIBE_TOOL_NAME, {"operation": "video_ai_remove_silence"})))
    assert payload["success"] is True
    assert payload["family"] == "video_ai_ops"
    assert payload["call"] == {
        "tool": "video_ai_ops",
        "operation": "video_ai_remove_silence",
        "params": "arguments exactly per inputSchema",
    }
    assert payload["cli"] == "kino video-ai-remove-silence"
    # byte-for-byte the schema the direct tool advertises in all mode
    from kinocut.tool_registry import load_operation_tool

    direct_schema = load_operation_tool("video_ai_remove_silence").parameters
    assert payload["inputSchema"] == direct_schema
    assert canonical_schema_bytes(payload["inputSchema"]) == canonical_schema_bytes(direct_schema)
    # discovery must restore the selected surface afterwards
    assert active_mode() == "default"
    assert _surface_names() == _default_surface_names()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")
def test_model_learns_and_exercises_an_optional_input_purely_from_discovery(sample_video):
    """R3 acceptance: learn a hidden operation's non-required argument from
    discovery alone — no source inspection — then exercise valid and invalid
    values for it through the family dispatcher."""

    configure_tool_surface()
    listing = _payload(asyncio.run(_call(DISCOVERY_TOOL_NAME, {"query": "video_ai_remove_silence"})))
    assert listing["count"] == 1
    row = listing["operations"][0]
    assert row["required_params"] == ["input_path", "output_path"]  # silence_threshold is NOT listed
    assert "inputSchema" not in row  # and cannot be guessed from the listing

    described = _payload(asyncio.run(_call(DESCRIBE_TOOL_NAME, {"operation": "video_ai_remove_silence"})))
    schema = described["inputSchema"]
    threshold = schema["properties"]["silence_threshold"]
    assert schema["required"] == ["input_path", "output_path"]
    assert threshold["type"] == "number"
    default = threshold["default"]
    assert isinstance(default, (int, float))

    # Exercise a valid, non-default value learned from the schema on scratch media.
    valid = default + 5 if default < 0 else default - 5
    out = str(Path(sample_video).with_name("learned.mp4"))
    ok = _payload(
        asyncio.run(
            _call(
                "video_ai_ops",
                {
                    "operation": "video_ai_remove_silence",
                    "params": {"input_path": sample_video, "output_path": out, "silence_threshold": valid},
                },
            )
        )
    )
    assert ok["success"] is True, ok

    # A schema-violating type for the same argument is rejected with a
    # family-usable hint naming the operation and a real CLI route.
    bad = _payload(
        asyncio.run(
            _call(
                "video_ai_ops",
                {
                    "operation": "video_ai_remove_silence",
                    "params": {"input_path": sample_video, "output_path": out, "silence_threshold": "not-a-number"},
                },
            )
        )
    )
    assert bad["success"] is False
    assert bad["error"]["type"] == "validation_error"
    message = bad["error"]["message"]
    assert "operation 'video_ai_remove_silence'" in message
    assert "kino video-ai-remove-silence" in message
    assert "ai-ops" not in message


def test_describe_operation_rejects_unknown_operations_without_invented_routes():
    configure_tool_surface()
    payload = _payload(asyncio.run(_call(DESCRIBE_TOOL_NAME, {"operation": "definitely_not_real"})))
    assert payload["success"] is False
    assert payload["error"]["code"] == "unknown_operation"
    message = payload["error"]["message"]
    assert message.endswith("; retry with call describe_operation with corrected parameters (MCP)")
    assert "kino " not in message


@pytest.mark.parametrize("operation", sorted(FAMILY_OF_OPERATION))
def test_described_schemas_cover_optional_arguments_everywhere(operation):
    """Every registry operation's contract is retrievable, and every operation
    that can write media carries the standard strict-boolean overwrite consent."""

    configure_tool_surface()
    payload = _payload(asyncio.run(_call(DESCRIBE_TOOL_NAME, {"operation": operation})))
    assert payload["success"] is True, operation
    schema = payload["inputSchema"]
    if operation in {"video_info", "video_info_detailed", "video_doctor"}:
        assert "overwrite" not in schema["properties"], operation
        return
    assert schema["properties"]["overwrite"]["type"] == "boolean", operation
    required = schema.get("required", [])
    optional = set(schema["properties"]) - set(required)
    assert optional, f"{operation} declares no optional argument to learn"


# --- retry routes: only CLI routes that exist (R4) --------------------------------------


def _kino_commands() -> frozenset[str]:
    """Enumerate the real kino subcommands straight from the parser."""

    from kinocut.cli.parser import build_parser

    subparsers = [a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction)]
    assert subparsers, "the kino CLI must register subcommands"
    return frozenset(subparsers[0].choices)


def test_every_family_cli_route_is_a_real_kino_subcommand():
    from kinocut.server_tools_families import _KINO_ROUTE, _family_invocation, cli_route_for_operation

    commands = _kino_commands()
    assert "video-ai-remove-silence" in commands  # the operation's real route ...
    assert "ai-ops" not in commands  # ... unlike the family-name-derived invention
    for operation, family in sorted(FAMILY_OF_OPERATION.items()):
        route = cli_route_for_operation(operation)
        if route is None:
            continue
        assert route in commands, (operation, route)
        for token in _KINO_ROUTE.findall(_family_invocation(family, operation)):
            assert token in commands, (operation, token)


def test_operation_without_a_cli_route_gets_an_mcp_only_hint():
    from kinocut.server_tools_families import _family_invocation, cli_route_for_operation

    commands = _kino_commands()
    routeless = [op for op in FAMILY_OF_OPERATION if cli_route_for_operation(op) is None]
    assert routeless, "the registry contains operations the CLI does not expose"
    operation = routeless[0]
    hint = _family_invocation(FAMILY_OF_OPERATION[operation], operation)
    assert hint.endswith("(MCP)")
    assert "kino " not in hint
    assert operation not in commands


def test_family_runtime_error_hints_are_retargeted_not_inherited():
    """A handler-time rejection under family dispatch must not point the
    caller at the direct tool, which is absent from the default wire."""

    configure_tool_surface()
    payload = _payload(
        asyncio.run(
            _call(
                "video_edit_ops",
                {"operation": "video_add_text", "params": {"input_path": "missing.mp4", "text": "hi", "crf": 99}},
            )
        )
    )
    assert payload["success"] is False
    message = payload["error"]["message"]
    assert message.startswith("crf must be 0-51, got 99")
    assert 'call video_edit_ops(operation="video_add_text", params={...})' in message
    assert "kino add-text" in message  # a real subcommand
    assert "call video_add_text " not in message


def test_code_specific_hints_survive_family_dispatch(sample_video):
    """Code-specific retry guidance (overwrite consent, new output path)
    survives family dispatch; only the direct tool name is retargeted."""

    configure_tool_surface()
    out = str(Path(sample_video).with_name("exists.mp4"))
    Path(out).write_bytes(Path(sample_video).read_bytes())
    payload = _payload(
        asyncio.run(
            _call(
                "video_edit_ops",
                {
                    "operation": "video_trim",
                    "params": {"input_path": sample_video, "start": 0.0, "end": 1.0, "output_path": out},
                },
            )
        )
    )
    assert payload["success"] is False
    assert payload["error"]["code"] == "output_exists"
    message = payload["error"]["message"]
    assert 'call video_edit_ops(operation="video_trim", params={...}) with overwrite=true' in message
    assert "--overwrite" in message
    assert "call video_trim " not in message


# --- isolation and concurrency ---------------------------------------------------------


def test_cold_server_mode_surfaces_are_exact():
    default = _subprocess_surface(None)
    assert default["mode"] == "default"
    assert set(default["names"]) == _default_surface_names()
    assert default["count"] == len(_default_surface_names()) == 18

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
    assert editor["count"] == len(expected) == 115  # 105 direct + 8 families + list_operations + describe_operation


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


def test_a_by_name_call_of_an_unlisted_operation_names_its_family():
    """1.x guidance calls profile tools by name; the wire stays closed but says where they went."""

    configure_tool_surface()
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(_call("video_quality_check", {"input_path": "unused.mp4"}))
    message = str(excinfo.value)
    assert message.startswith("Unknown tool: video_quality_check.")
    assert 'call video_ai_ops(operation="video_quality_check", params={...})' in message
    assert "describe_operation" in message
    with pytest.raises(ToolError, match=r"^Unknown tool: not_a_kinocut_tool$"):
        asyncio.run(_call("not_a_kinocut_tool", {}))


def test_invalid_parameter_errors_name_the_schema_fields_not_the_callers_keys():
    configure_tool_surface()
    direct = _payload(asyncio.run(_call(DESCRIBE_TOOL_NAME, {"zz_injected_key": "video_trim"})))
    message = direct["error"]["message"]
    assert "Required: operation. Accepted: operation." in message
    family = _payload(
        asyncio.run(
            _call(
                "video_edit_ops",
                {"operation": "video_audio_waveform", "params": {"input_path": "x.mp4", "zz_injected_key": 1}},
            )
        )
    )["error"]["message"]
    assert "Required: input_path." in family
    assert "Accepted: input_path, " in family
    assert "zz_injected_key" not in family and "zz_injected_key" not in message


def test_common_dispatch_aliases_are_forgiven():
    """Agents pass ``name`` for ``operation`` and ``args`` for ``params``; both resolve."""

    configure_tool_surface()
    described = _payload(asyncio.run(_call(DESCRIBE_TOOL_NAME, {"name": "video_trim"})))
    assert described["success"] is True and described["name"] == "video_trim"
    family = _payload(
        asyncio.run(_call("video_edit_ops", {"op": "video_audio_waveform", "args": {"zz_injected_key": 1}}))
    )
    assert family["error"]["code"] == "invalid_parameter", "the alias reached the operation's own validation"
    assert "for operation 'video_audio_waveform'" in family["error"]["message"]


def test_an_alias_never_overrides_the_declared_argument():
    configure_tool_surface()
    payload = _payload(asyncio.run(_call(DESCRIBE_TOOL_NAME, {"operation": "video_trim", "name": "video_merge"})))
    assert payload["success"] is False, "the stray alias stays an undeclared argument and is rejected"


def test_invalid_parameter_errors_show_one_line_call_shape():
    configure_tool_surface()
    direct = _payload(asyncio.run(_call(DESCRIBE_TOOL_NAME, {})))["error"]["message"]
    assert "Call: describe_operation(operation=...)." in direct
    family = _payload(asyncio.run(_call("video_edit_ops", {"operation": "video_audio_waveform", "params": {}})))[
        "error"
    ]["message"]
    assert 'Call: video_edit_ops(operation="video_audio_waveform", params={input_path=...}).' in family
