"""Tests for Story 5 batch variants + the keep-intermediates cleanup override.

Variants (plan §4) reuse the single ``sources``/``steps``/``outputs`` declaration:
one spec emits N distinct outputs, each rendered into its OWN ``@work`` run dir
with its OWN receipt (``workflow.variant`` set, ``feature_flags.variants`` true).
Selection rides the EXISTING surfaces via additive kwargs/flags only
(``variant=``/``--variant``, ``all_variants=``/``--all-variants``, ``save_receipt_dir``),
so the 124/103 public-surface drift counts are UNCHANGED.

Real renders shell out to FFmpeg and are marked ``@pytest.mark.slow``. Workspaces
live under ``tmp_path`` so every receipt path stays workspace-relative (privacy).
"""

from __future__ import annotations

import asyncio
import collections
import functools
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mcp_video.client import Client
from mcp_video.engine import probe
from mcp_video.errors import MCPVideoError
from mcp_video.server_tools_workflow import video_workflow_plan, video_workflow_render
from mcp_video.workflow import (
    apply_variant_overrides,
    plan_workflow,
    render_workflow,
    validate_workflow_spec,
    variant_ids,
)
from mcp_video.workflow import ops as ops_mod


# --- Specs + workspace -------------------------------------------------------


def _variant_spec() -> dict:
    """probe -> trim -> resize -> add_text; two variants resize to distinct sizes.

    Neither variant overrides the output path, so each variant's single declared
    output is AUTO-NAMED with the variant id (final.wide.mp4 / final.narrow.mp4).
    """
    return {
        "schema_version": 1,
        "name": "sized-shorts",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [
            {"id": "probe-hero", "op": "probe", "inputs": {"src": "@sources.hero"}},
            {
                "id": "trim-hero",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"start": 0, "duration": 1},
                "output": "@work/hero_trim.mp4",
            },
            {
                "id": "small",
                "op": "resize",
                "inputs": {"src": "@work/hero_trim.mp4"},
                "params": {"width": 320, "height": 240},
                "output": "@work/hero_small.mp4",
            },
            {
                "id": "caption",
                "op": "add_text",
                "inputs": {"src": "@work/hero_small.mp4"},
                "params": {"text": "Watch this"},
                "output": "@outputs.master",
            },
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
        "variants": [
            {"id": "wide", "overrides": {"steps.small.params": {"width": 480, "height": 360}}},
            {"id": "narrow", "overrides": {"steps.small.params": {"width": 160, "height": 120}}},
        ],
    }


def _write_spec(tmp_path: Path, spec: dict, name: str = "job.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _workspace(tmp_path: Path, sample_video: str) -> Path:
    (tmp_path / "input").mkdir(exist_ok=True)
    shutil.copy(sample_video, tmp_path / "input" / "hero.mp4")
    return tmp_path


# --- Spy fixture (proves a step's engine was/was not invoked) ----------------


@pytest.fixture
def op_spies(monkeypatch):
    """Count engine invocations; optionally sabotage an op's FIRST call.

    Mirrors the resume-suite fixture: ``calls`` is a Counter keyed by op name;
    set ``sabotage["op"] = "<op>"`` to make that op raise once, then run for real.
    """
    calls: collections.Counter[str] = collections.Counter()
    sabotage: dict[str, object] = {"op": None, "fired": False}

    def wrap(name: str, adapter):
        real = adapter.engine_fn

        @functools.wraps(real)
        def spy(*args, **kwargs):
            calls[name] += 1
            if sabotage["op"] == name and not sabotage["fired"]:
                sabotage["fired"] = True
                raise MCPVideoError("sabotaged step", error_type="processing_error", code="sabotaged_step")
            return real(*args, **kwargs)

        return replace(adapter, engine_fn=spy)

    for name, adapter in list(ops_mod.OP_ADAPTERS.items()):
        monkeypatch.setitem(ops_mod.OP_ADAPTERS, name, wrap(name, adapter))
    return calls, sabotage


# --- Override merge correctness (no render) ----------------------------------


def test_override_merges_params_and_names_output():
    merged = apply_variant_overrides(_variant_spec(), "wide")

    small = next(s for s in merged["steps"] if s["id"] == "small")
    assert small["params"] == {"width": 480, "height": 360}  # merged over base 320x240
    # single declared output auto-named with the variant id (no explicit override).
    assert merged["outputs"]["master"]["path"] == "output/final.wide.mp4"


def test_override_single_param_and_explicit_output_path():
    spec = _variant_spec()
    spec["variants"] = [
        {
            "id": "tall",
            "overrides": {
                "steps.small.params.width": 176,  # single-param merge (height untouched)
                "outputs.master.path": "output/custom_tall.mp4",  # explicit path -> no auto-suffix
            },
        }
    ]
    merged = apply_variant_overrides(spec, "tall")

    small = next(s for s in merged["steps"] if s["id"] == "small")
    assert small["params"] == {"width": 176, "height": 240}
    assert merged["outputs"]["master"]["path"] == "output/custom_tall.mp4"


def test_override_step_output_target():
    spec = _variant_spec()
    spec["variants"] = [{"id": "alt", "overrides": {"steps.trim-hero.output": "@work/alt_trim.mp4"}}]
    merged = apply_variant_overrides(spec, "alt")

    trim = next(s for s in merged["steps"] if s["id"] == "trim-hero")
    assert trim["output"] == "@work/alt_trim.mp4"


def test_variant_merge_does_not_duplicate_or_mutate_sources():
    base = _variant_spec()
    merged = apply_variant_overrides(base, "wide")

    # The variant reuses the single source declaration verbatim (no duplication).
    assert merged["sources"] == base["sources"] == {"hero": {"path": "input/hero.mp4"}}
    # Deep copy: the base spec object is never mutated by an override.
    assert base["steps"][2]["params"] == {"width": 320, "height": 240}
    assert base["outputs"]["master"]["path"] == "output/final.mp4"


def test_variant_ids_lists_declared_variants():
    assert variant_ids(_variant_spec()) == ["wide", "narrow"]
    assert variant_ids({"schema_version": 1, "sources": {}, "steps": []}) == []


# --- Fail-closed: unknown variant + malformed overrides ----------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"steps.ghost.params": {"width": 1}},  # unknown step id
        {"outputs.ghost.path": "x.mp4"},  # unknown output id
        {"sources.hero.path": "evil.mp4"},  # source is not a valid override root
        {"steps.small.params": "notadict"},  # params override must be an object
        {"outputs.master.path": 123},  # path must be a string
        {"steps.small": {"op": "convert"}},  # too-shallow / unsupported step target
    ],
)
def test_malformed_override_fails_closed(overrides):
    spec = _variant_spec()
    spec["variants"] = [{"id": "x", "overrides": overrides}]
    with pytest.raises(MCPVideoError) as exc:
        apply_variant_overrides(spec, "x")
    assert exc.value.code == "invalid_workflow_variant"


def test_unknown_variant_fails_closed():
    with pytest.raises(MCPVideoError) as exc:
        apply_variant_overrides(_variant_spec(), "does-not-exist")
    assert exc.value.code == "invalid_workflow_variant"


def test_override_unknown_param_fails_closed_post_merge(tmp_path):
    """A bad PARAM name survives the merge but is rejected by post-merge introspection."""
    spec = _variant_spec()
    spec["variants"] = [{"id": "x", "overrides": {"steps.small.params.bogus_param": 7}}]
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec), variant="x")
    assert exc.value.code == "invalid_workflow_params"


# --- Validate surface --------------------------------------------------------


def test_validate_reports_variants_and_stays_valid(tmp_path):
    verdict = validate_workflow_spec(_write_spec(tmp_path, _variant_spec()))

    assert verdict["valid"] is True
    assert verdict["variant"] is None
    assert verdict["variants"] == ["wide", "narrow"]


def test_validate_test_merges_every_declared_variant(tmp_path):
    """A spec with ONE broken variant fails `workflow-validate` even with no variant selected."""
    spec = _variant_spec()
    spec["variants"].append({"id": "broken", "overrides": {"steps.ghost.params": {"width": 1}}})
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, spec))
    assert exc.value.code == "invalid_workflow_variant"


def test_validate_single_variant_effective_spec(tmp_path):
    verdict = validate_workflow_spec(_write_spec(tmp_path, _variant_spec()), variant="wide")

    assert verdict["variant"] == "wide"
    assert verdict["output_paths"] == {"master": "output/final.wide.mp4"}


def test_validate_unknown_variant_fails_closed(tmp_path):
    with pytest.raises(MCPVideoError) as exc:
        validate_workflow_spec(_write_spec(tmp_path, _variant_spec()), variant="ghost")
    assert exc.value.code == "invalid_workflow_variant"


# --- Plan surface (dry-run parity) -------------------------------------------


def test_plan_variant_shows_effective_steps_and_output(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _variant_spec())

    plan = plan_workflow(spec_path, variant="narrow")

    assert plan["workflow"] == {"name": "sized-shorts", "variant": "narrow"}
    small = next(s for s in plan["steps"] if s["id"] == "small")
    assert small["inputs"] == {"src": "@work/hero_trim.mp4"}
    assert plan["outputs"] == [{"id": "master", "path": "output/final.narrow.mp4", "output_hash": None}]
    # dry-run purity: no media written.
    assert not (ws / "output" / "final.narrow.mp4").exists()


def test_plan_base_lists_all_variants(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    plan = plan_workflow(_write_spec(ws, _variant_spec()))

    assert plan["workflow"]["variant"] is None
    assert plan["variants"] == [{"id": "wide"}, {"id": "narrow"}]


def test_plan_unknown_variant_fails_closed(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    with pytest.raises(MCPVideoError) as exc:
        plan_workflow(_write_spec(ws, _variant_spec()), variant="ghost")
    assert exc.value.code == "invalid_workflow_variant"


# --- E2E: render distinct variants -------------------------------------------


@pytest.mark.slow
def test_single_variant_render_produces_distinct_output_and_receipt(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _variant_spec())

    receipt = render_workflow(spec_path, variant="wide", save_receipt=str(ws / "wide.json"))

    out = ws / "output" / "final.wide.mp4"
    assert out.is_file()
    assert probe(str(out)).width == 480 and probe(str(out)).height == 360
    assert receipt["workflow"] == {"name": "sized-shorts", "variant": "wide"}
    assert receipt["feature_flags"]["variants"] is True
    # The base output name is NOT produced by a variant render.
    assert not (ws / "output" / "final.mp4").exists()


@pytest.mark.slow
def test_all_variants_render_two_distinct_outputs(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _variant_spec())
    receipt_dir = ws / "receipts"

    batch = render_workflow(spec_path, all_variants=True, save_receipt_dir=str(receipt_dir))

    assert batch["receipt_kind"] == "workflow_batch"
    assert batch["status"] == "completed"
    assert batch["count"] == 2
    assert [r["workflow"]["variant"] for r in batch["variants"]] == ["wide", "narrow"]

    wide = ws / "output" / "final.wide.mp4"
    narrow = ws / "output" / "final.narrow.mp4"
    assert wide.is_file() and narrow.is_file()
    assert probe(str(wide)).width == 480
    assert probe(str(narrow)).width == 160

    # Per-variant receipts written to the dir and consistent with the batch.
    for variant_id, receipt in zip(("wide", "narrow"), batch["variants"], strict=True):
        on_disk = json.loads((receipt_dir / f"{variant_id}.json").read_text(encoding="utf-8"))
        assert on_disk == receipt
        assert on_disk["workflow"]["variant"] == variant_id
        assert on_disk["feature_flags"]["variants"] is True


@pytest.mark.slow
def test_all_variants_use_distinct_run_dirs_no_leakage(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    batch = render_workflow(_write_spec(ws, _variant_spec()), all_variants=True)

    work_dirs = [r["work_dir"] for r in batch["variants"]]
    assert len(set(work_dirs)) == len(work_dirs)  # no cross-variant @work collision
    for wd in work_dirs:
        assert wd.startswith("work/")


def test_all_variants_without_declared_variants_fails_closed(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec = _variant_spec()
    spec.pop("variants")
    with pytest.raises(MCPVideoError) as exc:
        render_workflow(_write_spec(ws, spec), all_variants=True)
    assert exc.value.code == "invalid_workflow_spec"


def test_variant_and_all_variants_are_mutually_exclusive(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    with pytest.raises(MCPVideoError) as exc:
        render_workflow(_write_spec(ws, _variant_spec()), variant="wide", all_variants=True)
    assert exc.value.code == "invalid_workflow_spec"


# --- Variant resume (sabotage B, resume B, A untouched) ----------------------


@pytest.mark.slow
def test_variant_resume_isolated_from_sibling_variant(tmp_path, sample_video, op_spies):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _variant_spec())
    _calls, sabotage = op_spies

    # Variant A ("wide") renders cleanly first.
    a = render_workflow(spec_path, variant="wide", save_receipt=str(ws / "wide.json"))
    wide_out = ws / "output" / "final.wide.mp4"
    assert wide_out.is_file()
    wide_hash_before = a["outputs"][0]["output_hash"]

    # Variant B ("narrow") is sabotaged at resize -> fails, keeps its intermediates.
    sabotage["op"] = "resize"
    with pytest.raises(MCPVideoError):
        render_workflow(spec_path, variant="narrow", save_receipt=str(ws / "narrow_fail.json"))
    fail = json.loads((ws / "narrow_fail.json").read_text(encoding="utf-8"))
    assert fail["status"] == "failed"
    assert fail["workflow"]["variant"] == "narrow"
    assert fail["work_dir"] != a["work_dir"]  # B has its own run dir

    # Resume B from its own receipt -> completes into B's output only.
    resume = render_workflow(
        spec_path, resume_receipt=str(ws / "narrow_fail.json"), variant="narrow"
    )
    narrow_out = ws / "output" / "final.narrow.mp4"
    assert narrow_out.is_file()
    assert probe(str(narrow_out)).width == 160
    assert resume["status"] == "completed"
    assert resume["feature_flags"]["resume_used"] is True
    assert resume["work_dir"] == fail["work_dir"]  # reused B's run dir, not A's

    # Variant A's output is untouched by any of B's activity.
    assert wide_out.is_file()
    from mcp_video.workflow.planner import _hash_if_exists

    assert _hash_if_exists(wide_out, {}) == wide_hash_before


def test_resume_variant_mismatch_fails_closed(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _variant_spec())
    # Handcraft a prior receipt for variant "narrow" with a matching spec_hash.
    import hashlib

    spec_hash = "sha256:" + hashlib.sha256(Path(spec_path).read_bytes()).hexdigest()
    prior = ws / "narrow.json"
    prior.write_text(
        json.dumps(
            {"spec_hash": spec_hash, "work_dir": "work/x", "steps": [], "workflow": {"variant": "narrow"}}
        ),
        encoding="utf-8",
    )
    # Resuming it while asking for a DIFFERENT variant fails closed.
    with pytest.raises(MCPVideoError) as exc:
        render_workflow(spec_path, resume_receipt=str(prior), variant="wide")
    assert exc.value.code == "resume_variant_mismatch"

    # Resuming a variant receipt as the BASE (variant=None) also mismatches.
    with pytest.raises(MCPVideoError) as exc2:
        render_workflow(spec_path, resume_receipt=str(prior))
    assert exc2.value.code == "resume_variant_mismatch"


# --- keep_intermediates override ---------------------------------------------


@pytest.mark.slow
def test_keep_intermediates_persists_files_and_records_policy(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _variant_spec())

    receipt = render_workflow(spec_path, keep_intermediates=True)

    manifest = receipt["cleanup_manifest"]
    assert manifest["policy"] == "keep-intermediates"
    assert manifest["cleaned"] is False
    assert manifest["intermediates"]  # trim + resize outputs tracked
    for rel in manifest["intermediates"]:
        assert (ws / rel).is_file()  # persisted despite success
    assert (ws / "output" / "final.mp4").is_file()


@pytest.mark.slow
def test_default_render_still_cleans_on_success(tmp_path, sample_video):
    """Regression: without keep_intermediates the default policy is unchanged."""
    ws = _workspace(tmp_path, sample_video)
    receipt = render_workflow(_write_spec(ws, _variant_spec()))

    manifest = receipt["cleanup_manifest"]
    assert manifest["policy"] == "clean-on-success"
    assert manifest["cleaned"] is True
    for rel in manifest["intermediates"]:
        assert not (ws / rel).exists()


@pytest.mark.slow
def test_keep_intermediates_variant_render(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    receipt = render_workflow(_write_spec(ws, _variant_spec()), variant="wide", keep_intermediates=True)

    assert receipt["cleanup_manifest"]["policy"] == "keep-intermediates"
    assert receipt["cleanup_manifest"]["cleaned"] is False
    for rel in receipt["cleanup_manifest"]["intermediates"]:
        assert (ws / rel).is_file()


# --- Privacy: workspace-relative paths only ----------------------------------


@pytest.mark.slow
def test_variant_receipts_are_workspace_relative(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    batch = render_workflow(_write_spec(ws, _variant_spec()), all_variants=True)
    text = json.dumps(batch)

    assert str(ws) not in text
    assert "/Users/" not in text
    assert "/home/" not in text
    for receipt in batch["variants"]:
        for output in receipt["outputs"]:
            assert not output["path"].startswith("/")
        assert not receipt["work_dir"].startswith("/")


# --- Cross-surface parity (MCP / CLI / Python) -------------------------------


@pytest.mark.slow
def test_mcp_render_variant_envelope(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    result = video_workflow_render(_write_spec(ws, _variant_spec()), variant="wide")

    assert result["success"] is True
    assert result["receipt_kind"] == "workflow"
    assert result["workflow"]["variant"] == "wide"


@pytest.mark.slow
def test_mcp_render_all_variants_envelope(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    result = video_workflow_render(_write_spec(ws, _variant_spec()), all_variants=True)

    assert result["success"] is True
    assert result["receipt_kind"] == "workflow_batch"
    assert result["count"] == 2


def test_mcp_plan_variant_envelope(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    result = video_workflow_plan(_write_spec(ws, _variant_spec()), variant="narrow")

    assert result["success"] is True
    assert result["workflow"]["variant"] == "narrow"


def test_mcp_render_unknown_variant_error_envelope(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    result = video_workflow_render(_write_spec(ws, _variant_spec()), variant="ghost")

    assert result["success"] is False
    assert result["error"]["code"] == "invalid_workflow_variant"
    assert "suggested_action" in result["error"]


@pytest.mark.slow
def test_client_render_variant_and_all(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _variant_spec())

    single = Client().workflow_render(spec_path, variant="narrow")
    assert single["workflow"]["variant"] == "narrow"
    assert (ws / "output" / "final.narrow.mp4").is_file()


@pytest.mark.slow
def test_cli_render_all_variants(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _variant_spec())
    receipt_dir = ws / "cli_receipts"

    completed = subprocess.run(
        [
            sys.executable, "-m", "mcp_video", "--format", "json",
            "workflow-render", "--spec", spec_path,
            "--all-variants", "--save-receipt-dir", str(receipt_dir),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["receipt_kind"] == "workflow_batch"
    assert payload["count"] == 2
    assert (receipt_dir / "wide.json").is_file()
    assert (receipt_dir / "narrow.json").is_file()


@pytest.mark.slow
def test_cli_render_variant_keep_intermediates_text(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _variant_spec())

    completed = subprocess.run(
        [
            sys.executable, "-m", "mcp_video",
            "workflow-render", "--spec", spec_path, "--variant", "wide", "--keep-intermediates",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Workflow Render" in completed.stdout
    # @work intermediates persisted under keep-intermediates.
    work_dirs = list((ws / "work").glob("*"))
    assert work_dirs and any(any(d.iterdir()) for d in work_dirs if d.is_dir())


def test_cli_plan_variant_text(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    completed = subprocess.run(
        [
            sys.executable, "-m", "mcp_video",
            "workflow-plan", "--spec", _write_spec(ws, _variant_spec()), "--variant", "wide",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Workflow Plan" in completed.stdout
    assert "No media rendered" in completed.stdout


# --- Drift counts UNCHANGED (variants ride existing surfaces) ----------------


def test_variants_do_not_change_public_surface_counts():
    from mcp_video.server import mcp

    tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert len(tool_names) == 124  # additive kwargs only — no new tools
    assert {"video_workflow_render", "video_workflow_plan", "video_workflow_validate"} <= tool_names


def test_variant_flags_do_not_add_cli_commands():
    import re

    result = subprocess.run(
        [sys.executable, "-m", "mcp_video", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    command_lists = re.findall(r"\{([^}]+)\}", result.stdout)
    command_list = max(command_lists, key=lambda value: len(value.split(",")))
    assert len(set(command_list.split(","))) == 103  # additive flags only — no new commands
