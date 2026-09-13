"""Focused public-surface tests for the local Revideo bridge."""

from __future__ import annotations

import asyncio
import ast
import inspect
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from kinocut.defaults import DEFAULT_REVIDEO_INSTALL_TIMEOUT, DEFAULT_REVIDEO_RENDER_TIMEOUT
from kinocut.errors import ValidationError
from kinocut.revideo_models import RevideoRenderResult

ROOT = Path(__file__).resolve().parents[1]
_NAMES = {"revideo_materialize", "revideo_install", "revideo_render", "revideo_render_job"}

_FACADE_EXPORTS = (
    "video_rescue_inspect",
    "video_rescue_plan",
    "video_rescue_render",
    "video_composition_plan",
    "video_creative_autopilot_plan",
    "video_remote_egress_plan",
    "video_restoration_plan",
    "video_semantic_query",
    "video_semantic_timeline",
    "video_timeline_edit_plan",
    "video_visual_transform_plan",
    "video_benchmark_run",
    "video_capabilities",
    "video_cost_ledger",
    "video_learning_report",
    "video_publish_gate",
    "video_recipe_capture",
    "video_review_decision",
    "video_review_package",
    "revideo_install",
    "revideo_materialize",
    "revideo_render",
    "revideo_render_job",
)


def _receipt() -> RevideoRenderResult:
    return RevideoRenderResult(
        project_dir="/work/bridge",
        output_path="/work/video.mp4",
        output_sha256="a" * 64,
        job_sha256="b" * 64,
        width=640,
        height=360,
        fps=10.0,
        frames=10,
        duration_seconds=1.0,
        render_seconds=2.5,
    )


def test_render_receipt_schema_describes_exact_job_bytes() -> None:
    description = RevideoRenderResult.model_json_schema()["properties"]["job_sha256"]["description"]
    assert description == "SHA-256 of the complete, bounded, exact on-disk src/job.json bytes."


def test_server_registers_exact_revideo_tools_and_defaults() -> None:
    from kinocut.server import mcp

    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    assert tools.keys() >= _NAMES
    assert tools["revideo_install"].inputSchema["properties"]["timeout"]["default"] == DEFAULT_REVIDEO_INSTALL_TIMEOUT
    assert tools["revideo_render"].inputSchema["properties"]["timeout"]["default"] == DEFAULT_REVIDEO_RENDER_TIMEOUT


def test_server_facade_exports_preserve_callable_identity_and_signatures() -> None:
    from kinocut import server, server_facade_exports, server_tools_revideo

    assert server_facade_exports.__all__ == _FACADE_EXPORTS
    for name in _FACADE_EXPORTS:
        assert getattr(server, name) is getattr(server_facade_exports, name)
    for name in _NAMES:
        facade_callable = getattr(server, name)
        registered_callable = getattr(server_tools_revideo, name)
        assert facade_callable is registered_callable
        assert inspect.signature(facade_callable) == inspect.signature(registered_callable)


def test_server_facade_exports_remain_declarative_and_ordered() -> None:
    path = ROOT / "kinocut" / "server_facade_exports.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = [node.module for node in tree.body if isinstance(node, ast.ImportFrom)]
    assignments = [target.id for node in tree.body if isinstance(node, ast.Assign) for target in node.targets]
    assert imports == [
        "server_tools_rescue",
        "server_tools_postrescue",
        "server_tools_release",
        "server_tools_revideo",
    ]
    assert assignments == ["__all__"]
    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in tree.body)


def test_mcp_success_envelopes(monkeypatch, tmp_path) -> None:
    from kinocut import revideo_engine
    from kinocut.server_tools_revideo import revideo_install, revideo_materialize, revideo_render

    monkeypatch.setattr(revideo_engine, "materialize_project", lambda *a, **k: tmp_path / "bridge")
    monkeypatch.setattr(revideo_engine, "install_deps", lambda *a, **k: None)
    monkeypatch.setattr(revideo_engine, "render", lambda *a, **k: _receipt())
    assert revideo_materialize(str(tmp_path / "bridge"), {}) == {
        "success": True,
        "project_dir": str(tmp_path / "bridge"),
    }
    assert revideo_install(str(tmp_path / "bridge"))["success"] is True
    payload = revideo_render(str(tmp_path / "bridge"), str(tmp_path / "video.mp4"))
    assert payload["success"] is True
    assert payload["output_sha256"] == "a" * 64
    assert payload["frames"] == 10


def test_mcp_known_error_is_serialized(monkeypatch, tmp_path) -> None:
    from kinocut import revideo_engine
    from kinocut.errors import RevideoProjectError
    from kinocut.server_tools_revideo import revideo_materialize

    def fail(*_args, **_kwargs):
        raise RevideoProjectError("bridge", "bad project")

    monkeypatch.setattr(revideo_engine, "materialize_project", fail)
    payload = revideo_materialize(str(tmp_path / "bridge"), {})
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_revideo_project"


def test_client_exposes_receipts_without_media_coercion(monkeypatch, tmp_path) -> None:
    from kinocut import Client, revideo_engine

    monkeypatch.setattr(revideo_engine, "render", lambda *a, **k: _receipt())
    client = Client()
    contract = client.inspect("revideo_render")
    assert contract["category"] == "report"
    assert contract["return_type"] == "RevideoRenderResult"
    assert client.revideo_render(tmp_path / "bridge", str(tmp_path / "video.mp4")).output_sha256 == "a" * 64


def test_client_methods_match_public_argument_names() -> None:
    from kinocut import Client

    expected = {
        "revideo_materialize": ("dest", "job", "scene_source"),
        "revideo_install": ("project_dir", "timeout"),
        "revideo_render": ("project_dir", "output_path", "timeout"),
        "revideo_render_job": (
            "job",
            "output_path",
            "work_dir",
            "scene_source",
            "install_timeout",
            "render_timeout",
        ),
    }
    for name, parameters in expected.items():
        assert tuple(inspect.signature(getattr(Client, name)).parameters)[1:] == parameters


def test_cli_parser_contract() -> None:
    from kinocut.cli.parser import build_parser

    parser = build_parser()
    args = parser.parse_args(["revideo-render-job", "out.mp4", "--job-json", '{"frames": 10}'])
    assert args.command == "revideo-render-job"
    assert args.output_path == "out.mp4"
    assert args.install_timeout == DEFAULT_REVIDEO_INSTALL_TIMEOUT
    assert args.render_timeout == DEFAULT_REVIDEO_RENDER_TIMEOUT
    with pytest.raises(SystemExit):
        parser.parse_args(["revideo-render-job", "out.mp4"])


def test_cli_rejects_non_object_before_engine(monkeypatch) -> None:
    from kinocut import revideo_engine
    from kinocut.cli.handlers_revideo import handle_revideo_commands

    monkeypatch.setattr(revideo_engine, "render_job", lambda *_a, **_k: pytest.fail("engine invoked"))
    args = Namespace(
        command="revideo-render-job",
        output_path="out.mp4",
        job_json="[]",
        work_dir=None,
        scene_source=None,
        install_timeout=1,
        render_timeout=1,
    )
    with pytest.raises(ValidationError, match="JSON object"):
        handle_revideo_commands(args, use_json=False)


@pytest.mark.parametrize("value", ["{", '"' + ("x" * 1_048_577) + '"'])
def test_cli_rejects_malformed_or_oversized_job_json(value, capsys) -> None:
    from kinocut.cli.handlers_revideo import _job

    with pytest.raises(SystemExit):
        _job(value, True)
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_json"


def test_cli_json_render_retains_complete_receipt(monkeypatch, capsys) -> None:
    from kinocut import revideo_engine
    from kinocut.cli.handlers_revideo import handle_revideo_commands

    monkeypatch.setattr(revideo_engine, "render", lambda *_a, **_k: _receipt())
    args = Namespace(command="revideo-render", project_dir="bridge", output_path="video.mp4", timeout=3)
    assert handle_revideo_commands(args, use_json=True) is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["project_dir"] == "/work/bridge"
    assert payload["output_sha256"] == "a" * 64


@pytest.mark.parametrize(
    "code",
    [
        "import kinocut",
        "import mcp_video",
        "from kinocut.cli.parser import build_parser; build_parser()",
        "import kinocut; kinocut.Client",
        "import kinocut.server",
    ],
)
def test_revideo_engine_stays_lazy_during_discovery(code: str) -> None:
    script = f"{code}; import sys; print('kinocut.revideo_engine' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert result.stdout.strip() == "False"


def test_distribution_sources_include_complete_template() -> None:
    required = {
        "package.json",
        "package-lock.json",
        "render.mjs",
        "tsconfig.json",
        "src/project.ts",
        "src/scene.ts",
        "src/job.json",
    }
    template = ROOT / "kinocut" / "revideo_template"
    assert required <= {str(path.relative_to(template)) for path in template.rglob("*") if path.is_file()}


def test_revideo_names_and_count_split_are_documented() -> None:
    claims = json.loads((ROOT / "docs" / "public_claims.json").read_text(encoding="utf-8"))
    assert claims["published_mcp_tools"] == 196
    assert claims["published_cli_commands"] == 167
    assert claims["development_mcp_tools"] == 201
    assert claims["development_cli_commands"] == 172
    surfaces = [
        ROOT / "docs" / "TOOLS.md",
        ROOT / "docs" / "CLI_REFERENCE.md",
        ROOT / "docs" / "PYTHON_CLIENT.md",
        ROOT / "skills" / "kinocut" / "SKILL.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in surfaces)
    for name in _NAMES:
        assert name in combined
    for name in ("revideo-materialize", "revideo-install", "revideo-render", "revideo-render-job"):
        assert name in combined
