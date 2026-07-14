"""Tests for fail-closed resumable render (``render_workflow(resume_receipt=...)``).

Resume semantics are §5a: spec_hash gate; a step is SKIPPED iff it is completed
AND its recorded input hashes still match AND (for output-producing ops) its
recorded output file still exists and re-hashes to the recorded hash; the first
step failing any check plus everything after re-runs.

The ``op_spies`` fixture wraps every op adapter with a call-counter (and an
optional first-call sabotage) so a test can PROVE a step was skipped (its engine
was not re-invoked) rather than merely re-rendered to the same bytes. Real
renders are ``@pytest.mark.slow``.
"""

from __future__ import annotations

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
from mcp_video.server_tools_workflow import video_workflow_render
from mcp_video.workflow import ops as ops_mod
from mcp_video.workflow import render_workflow


# --- Spy fixture -------------------------------------------------------------


@pytest.fixture
def op_spies(monkeypatch):
    """Count every engine invocation; optionally sabotage an op's FIRST call.

    Returns ``(calls, sabotage)``: ``calls`` is a Counter keyed by op name;
    set ``sabotage["op"] = "<op>"`` to make that op raise ``MCPVideoError`` the
    first time it runs (subsequent runs execute for real — the resume "fix").
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


# --- Specs + workspace -------------------------------------------------------


def _chain_spec() -> dict:
    """probe -> trim -> resize -> add_text; resize is the sabotage point."""
    return {
        "schema_version": 1,
        "name": "resume-chain",
        "sources": {"hero": {"path": "input/hero.mp4"}},
        "steps": [
            {"id": "p", "op": "probe", "inputs": {"src": "@sources.hero"}},
            {
                "id": "trim",
                "op": "trim",
                "inputs": {"src": "@sources.hero"},
                "params": {"start": 0, "duration": 1},
                "output": "@work/trim.mp4",
            },
            {
                "id": "small",
                "op": "resize",
                "inputs": {"src": "@work/trim.mp4"},
                "params": {"width": 320, "height": 240},
                "output": "@work/small.mp4",
            },
            {
                "id": "caption",
                "op": "add_text",
                "inputs": {"src": "@work/small.mp4"},
                "params": {"text": "Watch this"},
                "output": "@outputs.master",
            },
        ],
        "outputs": {"master": {"path": "output/final.mp4"}},
    }


def _write_spec(tmp_path: Path, spec: dict, name: str = "job.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _workspace(tmp_path: Path, sample_video: str) -> Path:
    (tmp_path / "input").mkdir(exist_ok=True)
    shutil.copy(sample_video, tmp_path / "input" / "hero.mp4")
    return tmp_path


def _fail_first(ws: Path, spec_path: str, op_spies) -> dict:
    """Run the chain once with ``resize`` sabotaged; return the failed receipt."""
    _calls, sabotage = op_spies
    sabotage["op"] = "resize"
    fail_receipt = ws / "fail.json"
    with pytest.raises(MCPVideoError):
        render_workflow(spec_path, save_receipt=str(fail_receipt))
    receipt = json.loads(fail_receipt.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed"
    return receipt


# --- E2E resume (skip-before, re-run-from) -----------------------------------


@pytest.mark.slow
def test_resume_skips_completed_and_reruns_from_failure(tmp_path, sample_video, op_spies):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _chain_spec())
    calls, _ = op_spies

    fail = _fail_first(ws, spec_path, op_spies)
    # trim completed and its intermediate was KEPT for resume.
    assert fail["resume_cursor"] == {"last_completed_step": "trim", "next_step": "small"}
    kept = ws / fail["cleanup_manifest"]["intermediates"][0]
    assert kept.is_file()
    assert calls["trim"] == 1 and calls["resize"] == 1  # resize was the sabotaged call

    resume = render_workflow(spec_path, resume_receipt=str(ws / "fail.json"), save_receipt=str(ws / "ok.json"))

    # Final output is real and correct.
    final = ws / "output" / "final.mp4"
    assert final.is_file()
    assert probe(str(final)).width == 320

    # Steps before the failure were SKIPPED (engine NOT re-invoked); N-onward re-ran.
    assert calls["trim"] == 1, "trim must not re-render on resume"
    assert calls["resize"] == 2, "resize (resume point) must re-run"
    assert calls["add_text"] == 1, "caption re-runs after the resume point"

    steps = {s["id"]: s for s in resume["steps"]}
    assert steps["p"].get("skipped") is True
    assert steps["trim"].get("skipped") is True
    assert steps["trim"]["status"] == "completed"  # skipped keeps completed status (§5a)
    assert "skipped" not in steps["small"]  # re-run
    assert "skipped" not in steps["caption"]

    assert resume["status"] == "completed"
    assert resume["feature_flags"]["resume_used"] is True
    assert resume["feature_flags"]["resumed_from"] == "small"
    assert resume["resume_cursor"] == {"last_completed_step": "caption", "next_step": None}
    # Resume succeeded -> intermediates cleaned.
    assert resume["cleanup_manifest"]["cleaned"] is True
    assert not kept.exists()


@pytest.mark.slow
def test_resume_tampered_intermediate_reruns_producing_step(tmp_path, sample_video, op_spies):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _chain_spec())
    calls, _ = op_spies

    fail = _fail_first(ws, spec_path, op_spies)
    kept = ws / fail["cleanup_manifest"]["intermediates"][0]  # trim's @work output
    kept.write_bytes(b"corrupted intermediate")  # tamper the persisted intermediate

    resume = render_workflow(spec_path, resume_receipt=str(ws / "fail.json"))

    # trim's recorded output_hash no longer matches -> trim re-runs (and everything after).
    assert calls["trim"] == 2, "tampered intermediate forces its producing step to re-run"
    assert calls["resize"] == 2
    steps = {s["id"]: s for s in resume["steps"]}
    assert "skipped" not in steps["trim"]
    assert resume["status"] == "completed"
    assert (ws / "output" / "final.mp4").is_file()


@pytest.mark.slow
def test_resume_deleted_work_dir_full_rerun(tmp_path, sample_video, op_spies):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _chain_spec())
    calls, _ = op_spies

    fail = _fail_first(ws, spec_path, op_spies)
    shutil.rmtree(ws / fail["work_dir"])  # prior intermediates gone

    resume = render_workflow(spec_path, resume_receipt=str(ws / "fail.json"))

    # Every render step re-runs because its kept output is gone.
    assert calls["trim"] == 2 and calls["resize"] == 2 and calls["add_text"] == 1
    assert resume["status"] == "completed"
    assert (ws / "output" / "final.mp4").is_file()


# --- Fail-closed gates -------------------------------------------------------


def test_resume_spec_hash_mismatch_fails_closed(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _chain_spec())
    # Handcraft a prior receipt whose spec_hash cannot match the current spec.
    stale = ws / "stale.json"
    stale.write_text(
        json.dumps({"spec_hash": "sha256:" + "0" * 64, "work_dir": "work/x", "steps": []}),
        encoding="utf-8",
    )
    with pytest.raises(MCPVideoError) as exc:
        render_workflow(spec_path, resume_receipt=str(stale))
    assert exc.value.code == "resume_spec_mismatch"


def test_resume_malformed_receipt_fails_closed(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _chain_spec())
    bad = ws / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(MCPVideoError) as exc:
        render_workflow(spec_path, resume_receipt=str(bad))
    assert exc.value.code == "invalid_workflow_receipt"


# --- Surface parity ----------------------------------------------------------


@pytest.mark.slow
def test_mcp_render_resume_envelope(tmp_path, sample_video, op_spies):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _chain_spec())
    _fail_first(ws, spec_path, op_spies)

    result = video_workflow_render(spec_path, str(ws / "fail.json"))

    assert result["success"] is True
    assert result["receipt_kind"] == "workflow"
    assert result["status"] == "completed"
    assert result["feature_flags"]["resume_used"] is True


def test_mcp_render_resume_error_envelope_on_mismatch(tmp_path, sample_video):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _chain_spec())
    stale = ws / "stale.json"
    stale.write_text(json.dumps({"spec_hash": "sha256:bad", "work_dir": "work/x", "steps": []}), encoding="utf-8")

    result = video_workflow_render(spec_path, str(stale))

    assert result["success"] is False
    assert result["error"]["code"] == "resume_spec_mismatch"


@pytest.mark.slow
def test_client_render_resume(tmp_path, sample_video, op_spies):
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _chain_spec())
    _fail_first(ws, spec_path, op_spies)

    receipt = Client().workflow_render(spec_path, resume_receipt=str(ws / "fail.json"))

    assert receipt["status"] == "completed"
    assert receipt["feature_flags"]["resume_used"] is True


@pytest.mark.slow
def test_cli_render_resume(tmp_path, sample_video, op_spies):
    """Fail receipt built in-process (sabotaged); the CLI subprocess resumes for real."""
    ws = _workspace(tmp_path, sample_video)
    spec_path = _write_spec(ws, _chain_spec())
    _fail_first(ws, spec_path, op_spies)  # produces fail.json + a real kept trim intermediate

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_video",
            "--format",
            "json",
            "workflow-render",
            "--spec",
            spec_path,
            "--resume",
            str(ws / "fail.json"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "completed"
    assert payload["feature_flags"]["resume_used"] is True
