from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.source_identity import stream_source_identity
from scripts import generate_golden_pack, golden_path, verify_onboarding_release as verify


COMMIT = "a" * 40
WORKFLOW_PATH = Path(__file__).resolve().parents[1] / "workflows" / "05-confidence-baseline" / "workflow.py"
WORKFLOW_SPEC = importlib.util.spec_from_file_location("confidence_baseline_workflow", WORKFLOW_PATH)
assert WORKFLOW_SPEC is not None and WORKFLOW_SPEC.loader is not None
confidence_workflow = importlib.util.module_from_spec(WORKFLOW_SPEC)
WORKFLOW_SPEC.loader.exec_module(confidence_workflow)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _valid_artifacts(output: Path, run_id: str = "fresh-run") -> None:
    source = output / "source.mp4"
    final = output / "final_clip.mp4"
    thumb = output / "checkpoint" / "thumbnail.jpg"
    frame = output / "checkpoint" / "storyboard" / "frame.jpg"
    for path in (source, final, thumb, frame):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
    source_identity = stream_source_identity(str(source))
    final_identity = stream_source_identity(str(final))
    quality = {
        "all_passed": True,
        "overall_score": 91.0,
        "checks": [
            {"name": "brightness", "passed": True},
            {"name": "temporal_motion", "passed": False},
        ],
    }
    checkpoint = {
        "quality": {"overall_score": 91.0},
        "review_required": True,
        "thumbnail": str(thumb),
        "storyboard": {"frames": [str(frame)]},
    }
    receipt = {
        "run_id": run_id,
        "candidate": {"package": "kinocut", "version": "1.15.1", "commit": COMMIT},
        "source_media": {
            "path": str(source),
            "sha256": source_identity.asset_id,
            "byte_size": source_identity.byte_size,
        },
        "tool_calls": [{"tool": "Client.trim"}],
        "review_artifacts": {"final_video": str(final), "final_sha256": final_identity.asset_id},
        "human_review": {"required": True, "status": "pending"},
        "known_limitations": ["Synthetic source media proves plumbing, not creative quality."],
    }
    _write_json(output / "quality.json", quality)
    _write_json(output / "release_checkpoint.json", checkpoint)
    _write_json(output / "video_receipt.json", receipt)


@pytest.mark.parametrize(
    "report",
    [
        "not-json",
        json.dumps({"summary": {}}),
        json.dumps({"summary": {"required_ok": 1}}),
        json.dumps({"summary": {"required_ok": False}}),
    ],
)
def test_doctor_report_fails_closed(report: str) -> None:
    with pytest.raises(golden_path.GoldenPathError):
        golden_path._validate_doctor(report)


def test_run_timeout_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], output="x" * 9000)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(golden_path.GoldenPathError, match="timed out") as caught:
        golden_path._run(["kino", "doctor"], timeout=1)
    assert len(str(caught.value)) < 1200


def test_run_start_error_is_typed_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("x" * 9000)))
    with pytest.raises(MCPVideoError, match="cannot start") as caught:
        golden_path._run(["missing"], timeout=1)
    assert len(str(caught.value)) < 1200


def test_huge_quality_scores_fail_with_typed_errors() -> None:
    with pytest.raises(golden_path.GoldenPathError, match="finite"):
        golden_path._finite_score(10**400, "quality")
    with pytest.raises(MCPVideoError, match="score"):
        confidence_workflow._validate_raw_quality(
            {"all_passed": True, "overall_score": 10**400, "checks": [{"name": "audio", "passed": True}]}
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda out: (out / "quality.json").write_text("{"), "quality.json"),
        (lambda out: (out / "release_checkpoint.json").write_text("[]"), "checkpoint"),
        (
            lambda out: _write_json(out / "quality.json", {"all_passed": False, "overall_score": 91, "checks": []}),
            "all_passed",
        ),
        (
            lambda out: _write_json(out / "quality.json", {"overall_score": 91, "checks": []}),
            "all_passed",
        ),
        (
            lambda out: _write_json(out / "quality.json", {"all_passed": True, "overall_score": 79, "checks": []}),
            "score",
        ),
        (
            lambda out: _write_json(
                out / "quality.json",
                {"all_passed": True, "overall_score": 91, "checks": [{"name": "audio", "passed": False}]},
            ),
            "non-advisory",
        ),
        (lambda out: (out / "checkpoint" / "thumbnail.jpg").unlink(), "thumbnail"),
        (lambda out: (out / "checkpoint" / "storyboard" / "frame.jpg").unlink(), "storyboard"),
        (lambda out: (out / "final_clip.mp4").unlink(), "final"),
    ],
)
def test_artifact_validation_rejects_false_green(tmp_path: Path, mutation, message: str) -> None:
    _valid_artifacts(tmp_path)
    mutation(tmp_path)
    with pytest.raises(golden_path.GoldenPathError, match=message):
        golden_path._validate_artifacts(tmp_path, "fresh-run", COMMIT)


def test_artifact_validation_rejects_stale_run(tmp_path: Path) -> None:
    _valid_artifacts(tmp_path, run_id="old-run")
    with pytest.raises(golden_path.GoldenPathError, match="run_id"):
        golden_path._validate_artifacts(tmp_path, "fresh-run", COMMIT)


def test_artifact_validation_accepts_current_strict_result(tmp_path: Path) -> None:
    _valid_artifacts(tmp_path)
    result = golden_path._validate_artifacts(tmp_path, "fresh-run", COMMIT)
    assert result[1]["overall_score"] == 91.0


def test_source_identity_change_is_rejected(tmp_path: Path) -> None:
    _valid_artifacts(tmp_path)
    (tmp_path / "source.mp4").write_bytes(b"changed")
    with pytest.raises(golden_path.GoldenPathError, match="source identity"):
        golden_path._validate_artifacts(tmp_path, "fresh-run", COMMIT)


def test_source_identity_must_be_the_task_owned_source(tmp_path: Path) -> None:
    output = tmp_path / "output"
    _valid_artifacts(output)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"honest outside source")
    identity = stream_source_identity(str(outside))
    receipt_path = output / "video_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["source_media"] = {
        "path": str(outside),
        "sha256": identity.asset_id,
        "byte_size": identity.byte_size,
    }
    _write_json(receipt_path, receipt)
    with pytest.raises(golden_path.GoldenPathError, match=r"source.*inside output|expected output path"):
        golden_path._validate_artifacts(output, "fresh-run", COMMIT)


def test_final_identity_and_containment_are_required(tmp_path: Path) -> None:
    output = tmp_path / "output"
    _valid_artifacts(output)
    receipt_path = output / "video_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    receipt["review_artifacts"]["final_video"] = str(outside)
    receipt["review_artifacts"]["final_sha256"] = stream_source_identity(str(outside)).asset_id
    _write_json(receipt_path, receipt)
    with pytest.raises(golden_path.GoldenPathError, match="inside output"):
        golden_path._validate_artifacts(output, "fresh-run", COMMIT)


@pytest.mark.parametrize("commit", ["short", "b" * 40])
def test_candidate_identity_must_match_checkout(tmp_path: Path, commit: str) -> None:
    _valid_artifacts(tmp_path)
    receipt_path = tmp_path / "video_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["candidate"]["commit"] = commit
    _write_json(receipt_path, receipt)
    with pytest.raises(golden_path.GoldenPathError, match="candidate commit"):
        golden_path._validate_artifacts(tmp_path, "fresh-run", COMMIT)


def test_spoofed_github_sha_and_unavailable_git_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    result = subprocess.CompletedProcess(["git"], 0, stdout=COMMIT + "\n", stderr="")
    monkeypatch.setattr(golden_path.subprocess, "run", lambda *args, **kwargs: result)
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    with pytest.raises(golden_path.GoldenPathError, match="GITHUB_SHA"):
        golden_path._commit_identity()
    monkeypatch.delenv("GITHUB_SHA")
    monkeypatch.setattr(golden_path.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("git")))
    with pytest.raises(golden_path.GoldenPathError, match="commit"):
        golden_path._commit_identity()


def test_confidence_workflow_commit_identity_is_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    success = subprocess.CompletedProcess(["git"], 0, stdout=COMMIT + "\n", stderr="")
    monkeypatch.setattr(confidence_workflow.subprocess, "run", lambda *args, **kwargs: success)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    assert confidence_workflow._commit_identity() == COMMIT
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    with pytest.raises(MCPVideoError, match="does not match"):
        confidence_workflow._commit_identity()
    monkeypatch.delenv("GITHUB_SHA")
    malformed = subprocess.CompletedProcess(["git"], 0, stdout="short\n", stderr="")
    monkeypatch.setattr(confidence_workflow.subprocess, "run", lambda *args, **kwargs: malformed)
    with pytest.raises(MCPVideoError, match="does not match"):
        confidence_workflow._commit_identity()
    monkeypatch.setattr(
        confidence_workflow.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing git")),
    )
    with pytest.raises(MCPVideoError, match="cannot be verified"):
        confidence_workflow._commit_identity()


def test_confidence_workflow_start_error_is_typed_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        confidence_workflow.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("x" * 9000)),
    )
    with pytest.raises(MCPVideoError, match="x") as caught:
        confidence_workflow._run(["missing-ffmpeg"])
    assert len(str(caught.value)) < 1200


def test_synthetic_generators_execute_the_same_shared_recipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    acceptance_calls: list[list[str]] = []
    confidence_calls: list[list[str]] = []

    def checked(command, **_kwargs):
        acceptance_calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ffmpeg version fixture\n", stderr="")

    monkeypatch.setattr(verify, "_checked", checked)
    monkeypatch.setattr(confidence_workflow, "_run", lambda command: confidence_calls.append(command))
    acceptance_source = tmp_path / "acceptance.mp4"
    confidence_source = tmp_path / "confidence.mp4"

    verify._generate_source(acceptance_source, tmp_path, 10)
    confidence_workflow._generate_source(confidence_source)

    assert [*acceptance_calls[0][:-1], "SOURCE"] == [*confidence_calls[0][:-1], "SOURCE"]


def test_confidence_workflow_stops_before_checkpoint_on_failed_raw_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This test targets raw quality; CI merge-SHA mismatch has separate coverage.
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    class FakeClient:
        checkpoint_called = False

        def info(self, path):
            return {"duration": 6, "width": 1280, "height": 720}

        def _media(self, output):
            Path(output).write_bytes(b"media")
            return SimpleNamespace(output_path=str(output))

        def trim(self, video, **kwargs):
            return self._media(kwargs["output"])

        resize = trim
        add_text = trim
        normalize_audio = trim
        convert = trim

        def quality_check(self, video, fail_on_warning):
            return {"all_passed": False, "overall_score": 90, "checks": [{"name": "audio", "passed": False}]}

        def release_checkpoint(self, *args, **kwargs):
            self.checkpoint_called = True
            return {}

    client = FakeClient()
    monkeypatch.setattr(confidence_workflow, "Client", lambda: client)
    monkeypatch.setattr(confidence_workflow, "OUTPUT_DIR", tmp_path / "output")
    confidence_workflow.OUTPUT_DIR.mkdir()
    monkeypatch.setattr(sys, "argv", [str(WORKFLOW_PATH), str(source)])
    with pytest.raises(MCPVideoError, match="raw quality"):
        confidence_workflow.main()
    assert client.checkpoint_called is False


def _configure_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    source = tmp_path / "source-output"
    pack = tmp_path / "pack"
    _valid_artifacts(source)
    claims = tmp_path / "claims.json"
    _write_json(claims, {"published_version": "1.15.1"})
    monkeypatch.setattr(generate_golden_pack, "SOURCE_OUTPUT", source)
    monkeypatch.setattr(generate_golden_pack, "PACK", pack)
    monkeypatch.setattr(generate_golden_pack, "ARTIFACTS", pack / "artifacts")
    monkeypatch.setattr(generate_golden_pack, "CLAIMS", claims)
    monkeypatch.setattr(generate_golden_pack, "_commit_identity", lambda: COMMIT)
    return source, pack


def test_skip_run_rejects_stale_evidence_without_overwriting_pack(tmp_path: Path, monkeypatch) -> None:
    source, pack = _configure_pack(tmp_path, monkeypatch)
    pack.mkdir()
    sample = pack / "sample_video_receipt.json"
    sample.write_text("curated", encoding="utf-8")
    (pack / "artifacts").mkdir()
    (pack / "artifacts" / "sentinel").write_text("curated", encoding="utf-8")
    (source / "quality.json").write_text("{}", encoding="utf-8")
    assert generate_golden_pack.main(["--skip-run"]) == 1
    assert sample.read_text() == "curated"
    assert (pack / "artifacts" / "sentinel").read_text() == "curated"


def test_skip_run_rejects_stale_candidate_without_overwriting_pack(tmp_path: Path, monkeypatch) -> None:
    source, pack = _configure_pack(tmp_path, monkeypatch)
    pack.mkdir()
    sample = pack / "sample_video_receipt.json"
    sample.write_bytes(b"curated sample")
    artifacts = pack / "artifacts"
    artifacts.mkdir()
    sentinel = artifacts / "sentinel"
    sentinel.write_bytes(b"curated artifacts")
    receipt_path = source / "video_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["candidate"]["commit"] = "b" * 40
    _write_json(receipt_path, receipt)
    assert generate_golden_pack.main(["--skip-run"]) == 1
    assert sample.read_bytes() == b"curated sample"
    assert sentinel.read_bytes() == b"curated artifacts"


def test_skip_run_preserves_integrity_fields_in_shareable_sample(tmp_path: Path, monkeypatch) -> None:
    _, pack = _configure_pack(tmp_path, monkeypatch)
    assert generate_golden_pack.main(["--skip-run"]) == 0
    sample = json.loads((pack / "sample_video_receipt.json").read_text())
    assert sample["run_id"] == "fresh-run"
    assert sample["candidate"]["commit"] == COMMIT
    assert sample["source_media"]["sha256"].startswith("sha256:")
    assert sample["review_artifacts"]["final_sha256"].startswith("sha256:")
    assert "synthetic" in sample["known_limitations"][0].lower()


def test_pack_copy_failure_preserves_curated_destination(tmp_path: Path, monkeypatch, capsys) -> None:
    _, pack = _configure_pack(tmp_path, monkeypatch)
    pack.mkdir()
    sample = pack / "sample_video_receipt.json"
    sample.write_text("curated", encoding="utf-8")
    artifacts = pack / "artifacts"
    artifacts.mkdir()
    (artifacts / "sentinel").write_text("curated", encoding="utf-8")
    monkeypatch.setattr(
        generate_golden_pack.shutil,
        "copy2",
        lambda *args: (_ for _ in ()).throw(OSError("x" * 9000)),
    )
    assert generate_golden_pack.main(["--skip-run"]) == 1
    assert sample.read_text() == "curated"
    assert (artifacts / "sentinel").read_text() == "curated"
    assert len(capsys.readouterr().err) < 1200


@pytest.mark.parametrize("failed_call", [1, 2, 3, 4])
def test_pack_publish_failure_restores_both_curated_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_call: int
) -> None:
    _, pack = _configure_pack(tmp_path, monkeypatch)
    pack.mkdir()
    sample = pack / "sample_video_receipt.json"
    sample.write_bytes(b"curated sample")
    artifacts = pack / "artifacts"
    artifacts.mkdir()
    (artifacts / "sentinel").write_bytes(b"curated artifacts")
    stage_root = tmp_path / "stage"
    stage_artifacts = stage_root / "artifacts"
    stage_artifacts.mkdir(parents=True)
    (stage_artifacts / "new").write_bytes(b"new artifacts")
    stage_sample = stage_root / "sample.json"
    stage_sample.write_bytes(b"new sample")
    original_replace = generate_golden_pack.os.replace
    calls = 0

    def fail_one_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == failed_call:
            raise OSError(f"replace failure {failed_call}")
        original_replace(source, destination)

    monkeypatch.setattr(generate_golden_pack.os, "replace", fail_one_replace)
    with pytest.raises(OSError, match="replace failure"):
        generate_golden_pack._publish(stage_artifacts, stage_sample)
    assert sample.read_bytes() == b"curated sample"
    assert (artifacts / "sentinel").read_bytes() == b"curated artifacts"


def test_pack_timeout_preserves_curated_destination(tmp_path: Path, monkeypatch) -> None:
    _, pack = _configure_pack(tmp_path, monkeypatch)
    pack.mkdir()
    sample = pack / "sample_video_receipt.json"
    sample.write_text("curated", encoding="utf-8")
    artifacts = pack / "artifacts"
    artifacts.mkdir()
    (artifacts / "sentinel").write_text("curated", encoding="utf-8")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"], stderr="slow")

    monkeypatch.setattr(generate_golden_pack.subprocess, "run", timeout)
    assert generate_golden_pack.main([]) == 1
    assert sample.read_text() == "curated"
    assert (artifacts / "sentinel").read_text() == "curated"
