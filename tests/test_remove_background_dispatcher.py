"""Fail-closed dispatcher + Kinocut-owned --info for hyperframes-remove-background."""

from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.hyperframes_engine import _SCHEMA, remove_background
from mcp_video.hyperframes_models import HyperframesJsonResult


def _make_completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["hyperframes"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _hyperframes_subcommand(cmd: list[str]) -> str:
    for index, value in enumerate(cmd):
        if Path(value).name in {"hyperframes", "hyperframes.cmd"}:
            return cmd[index + 1]
    raise AssertionError(f"hyperframes command not found in {cmd!r}")


def _mock_deps_ok():
    def _which(name: str):
        if name in ("node", "npm", "npx", "hyperframes"):
            return f"/usr/bin/{name}"
        return None

    return patch("mcp_video.hyperframes_engine.shutil.which", side_effect=_which)


def _hf_cutout_response() -> subprocess.CompletedProcess[str]:
    return _make_completed_process(stdout=json.dumps({"output": "/tmp/cutout.webm"}))


def _run_remove_background(**kwargs):
    with (
        _mock_deps_ok(),
        patch(
            "mcp_video.hyperframes_engine.subprocess.run",
            return_value=_hf_cutout_response(),
        ) as mock_run,
    ):
        result = remove_background("/tmp/input.mp4", output_path="/tmp/cutout.webm", **kwargs)
    return result, mock_run


def test_hf_schema_remove_background_has_no_model_flag():
    spec = _SCHEMA["remove-background"]
    assert "model" not in spec.get("flags", {})
    assert "model" not in spec.get("switches", {})
    assert "model" not in spec.get("positional", [])
    assert "model" not in spec.get("optional_positional", [])


def test_default_path_hf_argv_has_no_model_and_invokes_remove_background():
    result, mock_run = _run_remove_background()
    cmd = mock_run.call_args[0][0]
    assert mock_run.call_count == 1
    assert _hyperframes_subcommand(cmd) == "remove-background"
    assert "--model" not in cmd
    assert result.data["output"] == "/tmp/cutout.webm"
    assert result.data["model"] == "u2net_human_seg"
    assert result.data["backend"] == "hyperframes"


def test_explicit_u2net_human_seg_omits_model_flag():
    _result, mock_run = _run_remove_background(model="u2net_human_seg")
    cmd = mock_run.call_args[0][0]
    assert _hyperframes_subcommand(cmd) == "remove-background"
    assert "--model" not in cmd
    assert "--info" not in cmd


def test_mask_interval_1_is_not_object_only_on_hf_path():
    _result, mock_run = _run_remove_background(mask_interval=1)
    assert mock_run.call_count == 1
    assert "--model" not in mock_run.call_args[0][0]


def test_birefnet_never_calls_hyperframes_and_is_unavailable(monkeypatch):
    def _missing_extra():
        raise MCPVideoError(
            'Product/object cutouts require pip install "kinocut[object-matte]". Guide: docs/PRODUCT_MATTE.md.',
            error_type="dependency_error",
            code="missing_object_matte",
            docs_url="docs/PRODUCT_MATTE.md",
        )

    monkeypatch.setattr("mcp_video.object_matte.api.require_object_matte_deps", _missing_extra)
    with (
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        patch("mcp_video.hyperframes_ops._require_node") as mock_node,
        patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run,
        pytest.raises(MCPVideoError) as excinfo,
    ):
        remove_background("/tmp/input.mp4", model="birefnet-general")

    mock_op.assert_not_called()
    mock_node.assert_not_called()
    mock_run.assert_not_called()
    err = excinfo.value
    assert err.error_type == "dependency_error"
    assert err.code == "missing_object_matte"
    message = str(err)
    assert "kinocut[object-matte]" in message
    assert "PRODUCT_MATTE.md" in message
    assert "Cerafica" not in message
    assert err.docs_url == "docs/PRODUCT_MATTE.md"


def test_unknown_model_is_validation_error_with_no_inference():
    with (
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run,
        pytest.raises(MCPVideoError) as excinfo,
    ):
        remove_background("/tmp/input.mp4", model="nope")

    mock_op.assert_not_called()
    mock_run.assert_not_called()
    err = excinfo.value
    assert err.error_type == "validation_error"
    assert "nope" in str(err)
    assert "u2net_human_seg" in str(err)
    assert "birefnet-general" in str(err)
    assert "products-and-objects" in str(err)


def test_info_is_kinocut_owned_and_never_calls_hyperframes():
    with (
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        patch("mcp_video.hyperframes_ops._require_node") as mock_node,
        patch("mcp_video.hyperframes_engine.subprocess.run") as mock_run,
    ):
        result = remove_background(info=True)

    mock_op.assert_not_called()
    mock_node.assert_not_called()
    mock_run.assert_not_called()
    assert isinstance(result, HyperframesJsonResult)
    data = result.data
    assert isinstance(data, dict)
    assert data["defaultModel"] == "u2net_human_seg"
    assert "u2net_human_seg" in data["allowlistedModels"]
    assert "birefnet-general" in data["allowlistedModels"]
    models = data["models"]
    assert models["u2net_human_seg"]["subject"] == "people"
    assert models["birefnet-general"]["subject"] == "products-and-objects"
    assert models["birefnet-general"]["install"] == 'pip install "kinocut[object-matte]"'
    assert "maxFrames" in models["birefnet-general"]["limits"]
    assert "limits" not in data
    assert data["docs"] == "docs/PRODUCT_MATTE.md"
    cache = data["cache"]
    assert isinstance(cache, dict)
    assert "weightsCached" in cache
    assert cache["weightsCached"] in {True, False}
    assert "path" in cache


def test_info_works_without_input_path_and_ignores_model():
    result = remove_background(input_path=None, info=True, model="birefnet-general")
    assert result.data["defaultModel"] == "u2net_human_seg"
    assert "birefnet-general" in result.data["allowlistedModels"]


def test_missing_input_path_without_info_is_validation_error():
    with (
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        pytest.raises(MCPVideoError) as excinfo,
    ):
        remove_background(info=False)

    mock_op.assert_not_called()
    assert excinfo.value.error_type == "validation_error"


def test_object_only_mask_interval_on_hf_path_errors():
    with (
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        pytest.raises(MCPVideoError) as excinfo,
    ):
        remove_background("/tmp/input.mp4", mask_interval=3)

    mock_op.assert_not_called()
    assert excinfo.value.error_type == "validation_error"
    assert "mask_interval" in str(excinfo.value)


def test_equipment_flags_on_hf_path_error():
    with (
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        pytest.raises(MCPVideoError) as excinfo,
    ):
        remove_background("/tmp/input.mp4", equipment_overlay="/tmp/overlay.png")

    mock_op.assert_not_called()
    assert excinfo.value.error_type == "validation_error"

    with (
        patch("mcp_video.hyperframes_ops._hyperframes_op") as mock_op,
        pytest.raises(MCPVideoError) as excinfo,
    ):
        remove_background("/tmp/input.mp4", fail_if_equipment_on_subject=True)

    mock_op.assert_not_called()
    assert excinfo.value.error_type == "validation_error"


def test_cli_info_parses_without_input_path():
    from kinocut.cli.parser import build_parser

    args = build_parser().parse_args(["hyperframes-remove-background", "--info"])
    assert args.input_path is None
    assert args.info is True


def test_cli_parser_accepts_model_and_object_flags():
    from kinocut.cli.parser import build_parser

    args = build_parser().parse_args(
        [
            "hyperframes-remove-background",
            "sku.mp4",
            "--model",
            "birefnet-general",
            "--mask-interval",
            "3",
            "--equipment-overlay",
            "overlay.png",
            "--fail-if-equipment-on-subject",
        ]
    )
    assert args.input_path == "sku.mp4"
    assert args.model == "birefnet-general"
    assert args.mask_interval == 3
    assert args.equipment_overlay == "overlay.png"
    assert args.fail_if_equipment_on_subject is True


def test_cli_handler_passes_info_and_model(monkeypatch):
    captured: dict = {}

    def fake_remove_background(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return HyperframesJsonResult(command="remove-background", data={"defaultModel": "u2net_human_seg"})

    monkeypatch.setattr("kinocut.hyperframes_engine.remove_background", fake_remove_background)
    monkeypatch.setattr("kinocut.cli.handlers_hyperframes._out", lambda *a, **k: None)
    monkeypatch.setattr(
        "kinocut.cli.handlers_hyperframes._with_spinner",
        lambda _message, fn, *a, **k: fn(*a, **k),
    )

    from kinocut.cli.handlers_hyperframes import handle_hyperframes_commands
    from kinocut.cli.parser import build_parser

    args = build_parser().parse_args(["hyperframes-remove-background", "--info", "--model", "u2net_human_seg"])
    assert handle_hyperframes_commands(args, use_json=True)
    assert captured.get("info") is True
    assert captured.get("model") == "u2net_human_seg"
    assert captured["args"][0] is None


def test_client_signature_exposes_model_and_optional_input():
    from kinocut import Client

    signature = inspect.signature(Client.hyperframes_remove_background)
    assert "model" in signature.parameters
    assert "info" in signature.parameters
    assert signature.parameters["input_path"].default is not inspect.Parameter.empty


def test_mcp_schema_info_does_not_require_input_path():
    import asyncio

    from mcp_video.server import mcp

    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    schema = tools["hyperframes_remove_background"].inputSchema
    assert "model" in schema["properties"]
    assert "info" in schema["properties"]
    assert "input_path" not in schema.get("required", [])
