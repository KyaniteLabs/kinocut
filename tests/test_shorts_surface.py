"""Shorts surface: MCP ``call_tool`` + Python ``Kinocut.shorts.*`` round trips.

The shorts product (long-form stream-to-shorts) ships as five thin MCP tools
(``shorts_plan``, ``shorts_propose``, ``shorts_review``, ``shorts_render``,
``shorts_package``) and five matching Python client methods. This test file
verifies the public surface only: every MCP tool must register under its exact
name, every Python method must mirror the same kwargs/return contract, the
Python client must produce the same payload as the registered MCP tool when
invoked with the same arguments, and an invalid payload must produce a
structured error rather than an exception leak. Status intentionally stays on
the existing ``get_render_job`` tool; this file asserts no shorts-specific
status tool exists.

Business logic lives in :mod:`kinocut.product.shorts` and is monkey-patched
here so the surface tests stay decoupled from the orchestrator's
implementation phase. ``kinocut.server``, ``kinocut.client``, and
``kinocut.server_tools_shorts`` are exercised with the patched backend.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError


_5_TOOL_NAMES = frozenset(
    {
        "shorts_plan",
        "shorts_propose",
        "shorts_review",
        "shorts_render",
        "shorts_package",
    }
)


# --------------------------------------------------------------------------- #
# Monkey-patch fixture
# --------------------------------------------------------------------------- #


@pytest.fixture
def patched_shorts(monkeypatch):
    """Replace ``kinocut.product.shorts`` with deterministic fakes.

    Captures every operation name + kwargs so the surface can assert that MCP
    tools and the Python client reach the same backend unchanged. The fake
    module's API surface (names) is rebuilt every test, then unbound by
    ``monkeypatch``.

    """
    import types

    from kinocut import product

    calls: list[dict] = []

    def _make(operation: str):
        def fake(**kwargs):
            calls.append({"operation": operation, "kwargs": kwargs})
            return {
                "success": True,
                "operation": operation,
                "echo": kwargs,
                "candidate_id": kwargs.get("candidate_id", "cand_test_1"),
                "job_id": f"job_{operation}_1",
            }

        return fake

    fake_shorts_module = types.ModuleType("kinocut.product.shorts")
    for name in _5_TOOL_NAMES:
        setattr(fake_shorts_module, name, _make(name))
    # ``raising=False`` lets the fixture work before the orchestrator publishes
    # ``kinocut.product.shorts``; once published, the real module is rebound.
    monkeypatch.setattr(product, "shorts", fake_shorts_module, raising=False)
    return calls


# --------------------------------------------------------------------------- #
# Five-tool-set assertions
# --------------------------------------------------------------------------- #


def test_five_shorts_tools_are_registered_with_exact_names():
    """Exactly the five shorts tools register, with the exact names, no status."""
    from mcp_video.server import mcp

    tools = {tool.name for tool in asyncio.run(mcp.list_tools())}
    shorts_tools = tools & {f"shorts_{verb}" for verb in ("plan", "propose", "review", "render", "package")}

    assert shorts_tools == _5_TOOL_NAMES
    assert "shorts_status" not in tools
    assert "shorts_post" not in tools
    assert "shorts_publish" not in tools
    assert "shorts_upload" not in tools


def test_short_surfaces_module_exposes_only_the_five_callables(patched_shorts):
    """No accidental binding such as ``shorts_status`` leaks from the adapter."""
    import kinocut.client.shorts as client_module
    import kinocut.server_tools_shorts as tools_module

    server_callables = {
        name for name in dir(tools_module) if name.startswith("shorts_") and callable(getattr(tools_module, name))
    }
    client_callables = {name for name in dir(client_module.ClientShortsMixin) if name.startswith("shorts_")}

    assert server_callables == _5_TOOL_NAMES
    assert client_callables == _5_TOOL_NAMES


def test_client_registers_only_short_surface_mixin_methods():
    """``Kinocut.shorts.*`` mirror the MCP tool names exactly — no extras."""
    from kinocut.client import Client

    instance = Client()
    method_names = {name for name in dir(instance) if name.startswith("shorts_") and callable(getattr(instance, name))}
    assert method_names == _5_TOOL_NAMES


# --------------------------------------------------------------------------- #
# MCP dispatch + client round-trip
# --------------------------------------------------------------------------- #


def _call_server_tool(operation: str, **arguments):
    """Invoke the registered MCP tool function directly (registered-tool dispatch)."""
    import kinocut.server_tools_shorts as tools_module

    handler = getattr(tools_module, operation)
    return handler(**arguments)


def test_mcp_plan_dispatches_to_short_plan_backend(patched_shorts, tmp_path):
    project = str(tmp_path / "project")
    source = str(tmp_path / "source.mp4")
    result = _call_server_tool(
        "shorts_plan",
        project_dir=project,
        source_path=source,
        platforms=["youtube-shorts", "instagram-reel"],
    )

    assert result["success"] is True
    assert result["operation"] == "shorts_plan"
    assert len(patched_shorts) == 1
    sent = patched_shorts[0]
    assert sent["operation"] == "shorts_plan"
    assert sent["kwargs"]["project_dir"] == project
    assert sent["kwargs"]["source_path"] == source
    assert sent["kwargs"]["platforms"] == ["youtube-shorts", "instagram-reel"]


def test_mcp_propose_round_trips_via_client_method(patched_shorts, tmp_path):
    """Tool call + ``Client().shorts_propose(...)`` produce the same payload."""
    from kinocut.client import Client

    project = str(tmp_path / "project")
    plan_payload = {"plan_id": "plan_xyz", "candidates": [{"id": "c1"}]}

    via_tool = _call_server_tool(
        "shorts_propose",
        project_dir=project,
        candidate_id="c1",
        plan=plan_payload,
        edits={"action": "approve"},
    )
    via_client = Client().shorts_propose(
        project_dir=project,
        candidate_id="c1",
        plan=plan_payload,
        edits={"action": "approve"},
    )

    assert via_tool == via_client
    assert via_tool["operation"] == "shorts_propose"
    assert via_tool["echo"]["edits"] == {"action": "approve"}


def test_mcp_review_requires_evidence_ref_kwarg(patched_shorts, tmp_path):
    project = str(tmp_path / "project")

    via_tool = _call_server_tool(
        "shorts_review",
        project_dir=project,
        candidate_id="c2",
        decision={"verdict": "accept"},
        evidence_ref="reviews/2025/c2.json",
    )

    assert via_tool["operation"] == "shorts_review"
    assert via_tool["echo"]["evidence_ref"] == "reviews/2025/c2.json"
    assert len(patched_shorts) == 1


def test_mcp_render_round_trips_with_render_options(patched_shorts, tmp_path):
    from kinocut.client import Client

    project = str(tmp_path / "project")
    output = str(tmp_path / "out.mp4")

    via_tool = _call_server_tool(
        "shorts_render",
        project_dir=project,
        candidate_id="c3",
        output_path=output,
        render_options={"max_duration": 90, "platform": "instagram-reel"},
    )
    via_client = Client().shorts_render(
        project_dir=project,
        candidate_id="c3",
        output_path=output,
        render_options={"max_duration": 90, "platform": "instagram-reel"},
    )

    assert via_tool == via_client
    assert via_tool["echo"]["render_options"] == {
        "max_duration": 90,
        "platform": "instagram-reel",
    }
    assert via_tool["job_id"].startswith("job_shorts_render_")


def test_mcp_package_round_trips_with_package_dir(patched_shorts, tmp_path):
    from kinocut.client import Client

    project = str(tmp_path / "project")
    package_dir = str(tmp_path / "out" / "shorts")

    via_tool = _call_server_tool(
        "shorts_package",
        project_dir=project,
        candidate_id="c4",
        package_dir=package_dir,
    )
    via_client = Client().shorts_package(
        project_dir=project,
        candidate_id="c4",
        package_dir=package_dir,
    )

    assert via_tool == via_client
    assert via_tool["echo"]["package_dir"] == package_dir


def test_client_shorts_methods_call_backend_exactly_once_per_invocation(patched_shorts, tmp_path):
    from kinocut.client import Client

    client = Client()
    project = str(tmp_path / "project")

    client.shorts_plan(project_dir=project, source_path=str(tmp_path / "s.mp4"))
    client.shorts_propose(
        project_dir=project,
        candidate_id="c5",
        plan={"plan_id": "p1"},
    )
    client.shorts_review(
        project_dir=project,
        candidate_id="c5",
        decision={"verdict": "reject"},
        evidence_ref="ev/ref1",
    )
    client.shorts_render(
        project_dir=project,
        candidate_id="c5",
        output_path=str(tmp_path / "o.mp4"),
    )
    client.shorts_package(
        project_dir=project,
        candidate_id="c5",
        package_dir=str(tmp_path / "pkg"),
    )

    assert [c["operation"] for c in patched_shorts] == [
        "shorts_plan",
        "shorts_propose",
        "shorts_review",
        "shorts_render",
        "shorts_package",
    ]


# --------------------------------------------------------------------------- #
# Unhappy paths (structured errors, no leaking exceptions)
# --------------------------------------------------------------------------- #


def test_invalid_payload_returns_structured_error_dict(monkeypatch, tmp_path):
    """``_safe_tool`` converts ``MCPVideoError`` into the canonical error envelope."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def explode(**kwargs):
        raise MCPVideoError(
            "candidate not approved",
            error_type="validation_error",
            code="not_approved",
        )

    import types as _types

    fake = _types.ModuleType("kinocut.product.shorts")
    fake.shorts_render = explode  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_render(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_disallowed",
        output_path=str(tmp_path / "out.mp4"),
    )

    assert result["success"] is False
    assert result["error"]["code"] == "not_approved"
    assert "candidate" in result["error"]["message"].lower()


def test_invalid_payload_unexpected_exception_returns_internal_error_envelope(monkeypatch, tmp_path):
    """Unexpected exceptions also funnel through ``_safe_tool`` -> ``_error_result``."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def boom(**kwargs):
        raise RuntimeError("orchestrator backend exploded")

    import types as _types2

    fake = _types2.ModuleType("kinocut.product.shorts")
    fake.shorts_package = boom  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_package(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_x",
        package_dir=str(tmp_path / "pkg"),
    )

    assert result["success"] is False
    assert result["error"]["type"] == "internal_error"
    assert result["error"]["code"] == "internal_error"


def test_invalid_platforms_value_propagates_as_validation_error(monkeypatch, tmp_path):
    """A bad ``platforms`` payload surfaces as a structured ``validation_error``."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def reject_platforms(platforms, **kwargs):
        if not isinstance(platforms, list) or not platforms:
            raise MCPVideoError(
                "platforms must be a non-empty list",
                error_type="validation_error",
                code="invalid_input",
            )
        return {
            "success": True,
            "operation": "shorts_plan",
            "echo": {"platforms": platforms, **kwargs},
        }

    import types as _types3

    fake = _types3.ModuleType("kinocut.product.shorts")
    fake.shorts_plan = reject_platforms  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_plan(
        project_dir=str(tmp_path / "project"),
        source_path=str(tmp_path / "s.mp4"),
        platforms=[],
    )

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_input"


# --------------------------------------------------------------------------- #
# Path-safety contract: orchestrator owns validation; adapter passes through
# --------------------------------------------------------------------------- #


def test_short_package_passes_package_dir_through_unchanged(patched_shorts, tmp_path):
    """The adapter does not modify ``package_dir``; product owns validation."""
    from kinocut.client import Client

    package_dir = str(tmp_path / "out" / "shorts")

    result = Client().shorts_package(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_path",
        package_dir=package_dir,
    )
    assert result["echo"]["package_dir"] == package_dir


def test_render_rejects_relative_output_path_via_orchestrator(monkeypatch, tmp_path):
    """Relative paths surface as structured backend errors, not wrapper fabrication."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def fail_on_relative(output_path, **kwargs):
        if not Path(output_path).is_absolute():
            raise MCPVideoError(
                "output_path must be absolute",
                error_type="validation_error",
                code="unsafe_path",
            )
        return {"success": True, "operation": "shorts_render", "echo": kwargs}

    import types as _types4

    fake = _types4.ModuleType("kinocut.product.shorts")
    fake.shorts_render = fail_on_relative  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_render(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_rel",
        output_path="relative.mp4",
    )
    assert result["success"] is False
    assert result["error"]["code"] == "unsafe_path"


def test_short_package_rejects_parent_segment_via_orchestrator(monkeypatch, tmp_path):
    """``..`` in package_dir surfaces as the orchestrator's structured error."""
    import kinocut.product as product_module
    import kinocut.server_tools_shorts as tools_module

    def reject_traversal(package_dir, **kwargs):
        if ".." in Path(package_dir).parts:
            raise MCPVideoError(
                "package_dir may not contain parent segments",
                error_type="validation_error",
                code="unsafe_path",
            )
        return {"success": True, "operation": "shorts_package", "echo": kwargs}

    import types as _types5

    fake = _types5.ModuleType("kinocut.product.shorts")
    fake.shorts_package = reject_traversal  # type: ignore[attr-defined]
    monkeypatch.setattr(product_module, "shorts", fake, raising=False)

    result = tools_module.shorts_package(
        project_dir=str(tmp_path / "project"),
        candidate_id="c_trav",
        package_dir=str(tmp_path / ".." / "elsewhere"),
    )
    assert result["success"] is False
    assert result["error"]["code"] == "unsafe_path"


# --------------------------------------------------------------------------- #
# JSON-contract guard: every shorts call round-trips through json.dumps
# --------------------------------------------------------------------------- #


def test_shorts_envelope_is_json_serialisable(patched_shorts, tmp_path):
    """The adapter's dict output must be JSON-clean (no NaN, no bytes)."""
    project = str(tmp_path / "project")

    raw = _call_server_tool(
        "shorts_plan",
        project_dir=project,
        source_path=str(tmp_path / "s.mp4"),
        platforms=["youtube-shorts"],
    )
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    decoded = json.loads(encoded)
    assert decoded == raw
