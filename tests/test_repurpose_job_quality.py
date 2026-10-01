"""Completion, frozen-policy and artifact-binding controls for durable repurpose."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.projectstore import open_project, render_jobs, render_runner
from kinocut.projectstore.repurpose import durable_repurpose
from kinocut.projectstore import repurpose_policy as gate
from kinocut import quality_guardrails
from kinocut import engine_repurpose


def _job(tmp_path, monkeypatch, **options):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source media")
    ack = durable_repurpose(str(source), str(tmp_path / "project"), platforms=["youtube"], start=False, **options)
    project = open_project(tmp_path / "project")
    job = render_jobs.get_render_job(project, ack["job_id"])
    spec_path = render_jobs.job_spec_path(project, job.job_id)
    spec = json.loads(spec_path.read_text())
    output = spec_path.parent / spec["outputs"]["out0"]["path"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"actual rendered media")
    digest = "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()
    receipt = {
        "status": "completed",
        "sources": [{"id": "src0", "resolved": spec["sources"]["src0"]["path"], "source_hash": ack["source_digest"]}],
        "outputs": [{"id": "out0", "path": spec["outputs"]["out0"]["path"], "output_hash": digest}],
        "versions": {"kinocut": "fixture", "ffmpeg": "fixture"},
        "steps": [{"id": "resize_out0", "status": "completed", "output_hash": digest}],
    }
    render_jobs.mark_running(project, job.job_id, 424242)
    monkeypatch.setattr(render_runner, "render_workflow", lambda **_: receipt)
    return project, ack, receipt, output


def _reviews(monkeypatch):
    monkeypatch.setattr(
        engine_repurpose, "thumbnail", lambda video, output_path: SimpleNamespace(output_path=output_path)
    )
    monkeypatch.setattr(
        engine_repurpose, "storyboard", lambda *args, **kwargs: SimpleNamespace(model_dump=lambda: {"frames": []})
    )


@pytest.mark.parametrize("score, outcome", [(79.99, "failed"), (80, "succeeded")])
def test_worker_applies_quality_before_terminal_success(tmp_path, monkeypatch, score, outcome):
    project, ack, _, _ = _job(tmp_path, monkeypatch)
    _reviews(monkeypatch)
    monkeypatch.setattr(
        quality_guardrails,
        "quality_check",
        lambda *a, **kw: {"overall_score": score, "checks": [], "recommendations": []},
    )
    assert render_runner.run_job(project, ack["job_id"]) == outcome
    head = render_jobs.get_render_job(project, ack["job_id"])
    assert head.status.value == outcome
    if outcome == "failed":
        assert head.error_code == "quality_gate_failed"
    else:
        result = json.loads(render_jobs.job_receipt_path(project, ack["job_id"]).read_text())
        assert result["repurpose_release"]["status"] == "passed"
        assert result["repurpose_release"]["policy"]["min_score"] == 80
        assert result["repurpose_release"]["outputs"][0]["release_checkpoint"]["review_required"] is True
        assert str(tmp_path) not in json.dumps(result["repurpose_release"])


def test_skip_checkpoint_discloses_no_evaluation_and_ack_matches_artifact(tmp_path, monkeypatch):
    project, ack, _, output = _job(tmp_path, monkeypatch, include_release_checkpoint=False)
    monkeypatch.setattr(gate, "_release_checkpoint", lambda *a: pytest.fail("checkpoint was not skipped"))
    assert project.root / ack["clips"][0]["output"] == output
    assert render_runner.run_job(project, ack["job_id"]) == "succeeded"
    result = json.loads(render_jobs.job_receipt_path(project, ack["job_id"]).read_text())
    assert result["repurpose_release"]["status"] == "not_evaluated"
    assert "release_checkpoint" not in result["repurpose_release"]["outputs"][0]


def test_unavailable_measurement_cannot_succeed(tmp_path, monkeypatch):
    project, ack, _, _ = _job(tmp_path, monkeypatch)

    def unavailable(*args):
        raise MCPVideoError("measurement unavailable", error_type="dependency_error", code="measurement_unavailable")

    monkeypatch.setattr(gate, "_release_checkpoint", unavailable)
    assert render_runner.run_job(project, ack["job_id"]) == "failed"
    assert render_jobs.get_render_job(project, ack["job_id"]).error_code == "measurement_unavailable"


@pytest.mark.parametrize(
    "damage", ["missing", "changed", "wrong_path", "duplicate", "policy", "source", "missing_source", "malformed_id"]
)
def test_missing_changed_or_unbound_outputs_fail_closed(tmp_path, monkeypatch, damage):
    project, ack, receipt, output = _job(tmp_path, monkeypatch, include_release_checkpoint=False)
    if damage == "missing":
        output.unlink()
    elif damage == "changed":
        output.write_bytes(b"replaced")
    elif damage == "wrong_path":
        receipt["outputs"][0]["path"] = "other.mp4"
    elif damage == "duplicate":
        receipt["outputs"].append(dict(receipt["outputs"][0]))
    elif damage in {"source", "missing_source"}:
        source = render_jobs.job_spec_path(project, ack["job_id"]).parent / receipt["sources"][0]["resolved"]
        if damage == "missing_source":
            source.unlink()
        else:
            source.write_bytes(b"replaced source")
    elif damage == "malformed_id":
        receipt["outputs"][0]["id"] = []
    else:
        path = render_jobs.job_spec_path(project, ack["job_id"])
        spec = json.loads(path.read_text())
        spec["repurpose_release_policy"]["min_score"] = 0
        path.write_text(json.dumps(spec))
    assert render_runner.run_job(project, ack["job_id"]) == "failed"
    assert render_jobs.get_render_job(project, ack["job_id"]).error_code == "repurpose_release_evidence_invalid"


@pytest.mark.parametrize("score", [True, False, float("nan"), float("inf"), -1, 101, 10**1000, "not a score"])
def test_invalid_policy_rejects_before_enqueue(tmp_path, score):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    project = tmp_path / "project"
    with pytest.raises(MCPVideoError) as failure:
        durable_repurpose(str(source), str(project), start=False, min_score=score)
    assert failure.value.code == "invalid_parameter"
    assert not project.exists()


def test_numeric_compatibility_and_resume_keep_frozen_threshold(tmp_path, monkeypatch):
    project, ack, _, _ = _job(tmp_path, monkeypatch, min_score="85")
    assert ack["release_policy"]["min_score"] == 85
    monkeypatch.setattr(
        gate,
        "_release_checkpoint",
        lambda *a: (_ for _ in ()).throw(MCPVideoError("below threshold", code="quality_gate_failed")),
    )
    assert render_runner.run_job(project, ack["job_id"]) == "failed"
    before = render_jobs.job_spec_path(project, ack["job_id"]).read_bytes()
    render_jobs.resume_render_job(project, ack["job_id"])
    assert render_jobs.job_spec_path(project, ack["job_id"]).read_bytes() == before


def test_invalid_checkpoint_flag_rejects_before_enqueue(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    with pytest.raises(MCPVideoError):
        durable_repurpose(str(source), str(tmp_path / "project"), start=False, include_release_checkpoint="false")
    assert not (tmp_path / "project").exists()


def test_real_render_ack_and_completed_receipt_name_the_same_artifact(sample_video, tmp_path):
    ack = durable_repurpose(
        sample_video,
        str(tmp_path / "project"),
        platforms=["instagram-post"],
        start=False,
        include_release_checkpoint=False,
    )
    project = open_project(tmp_path / "project")
    render_jobs.mark_running(project, ack["job_id"], 424242)
    assert render_runner.run_job(project, ack["job_id"]) == "succeeded"
    receipt = json.loads(render_jobs.job_receipt_path(project, ack["job_id"]).read_text())
    frozen_dir = render_jobs.job_spec_path(project, ack["job_id"]).parent
    actual = project.root / ack["clips"][0]["output"]
    assert actual.is_file()
    assert frozen_dir / receipt["outputs"][0]["path"] == actual
    assert receipt["outputs"][0]["output_hash"] == "sha256:" + hashlib.sha256(actual.read_bytes()).hexdigest()


@pytest.mark.parametrize("target", ["output", "source"])
def test_artifact_changed_during_checkpoint_cannot_succeed(tmp_path, monkeypatch, target):
    project, ack, receipt, output = _job(tmp_path, monkeypatch)
    if target == "source":
        output = render_jobs.job_spec_path(project, ack["job_id"]).parent / receipt["sources"][0]["resolved"]

    def replace_during_checkpoint(*args):
        output.write_bytes(b"different media")
        return {"quality": {"all_passed": True}, "review_required": True}

    monkeypatch.setattr(gate, "_release_checkpoint", replace_during_checkpoint)
    assert render_runner.run_job(project, ack["job_id"]) == "failed"
    assert render_jobs.get_render_job(project, ack["job_id"]).error_code == "repurpose_release_evidence_invalid"
