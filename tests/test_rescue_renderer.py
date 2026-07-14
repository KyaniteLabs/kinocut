"""Renderer approval, staleness, cancellation, and promotion semantics."""

from __future__ import annotations

import builtins
import hashlib
import json
import shutil
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.rescue.capabilities import snapshot_capabilities
from mcp_video.rescue.planner import plan_rescue
from mcp_video.rescue.renderer import render_rescue
from mcp_video.rescue.models import (
    Disposition,
    Finding,
    Metric,
    Repair,
    RescuePlan,
    VerificationCheck,
    canonical_payload,
)
from mcp_video.rescue.inspector import inspect_rescue


def _planned_fixture(tmp_path, sample_video):
    source = tmp_path / "input" / "clip.mp4"
    source.parent.mkdir(parents=True)
    shutil.copy2(sample_video, source)
    output = tmp_path / "output"
    plan_path = output / "plan.json"
    plan = plan_rescue(str(source), str(output), save_plan=str(plan_path))
    return source, plan_path, plan


def _caption_capabilities(*, available: bool, model_sha256: str | None = None):
    capabilities = deepcopy(snapshot_capabilities(find_spec=lambda name: None))
    capabilities["whisper"] = {
        "available": available,
        "version": "20250625" if available else None,
        "executor": "openai-whisper",
    }
    capabilities["whisper_models"] = {"base": {"available": available, "sha256": model_sha256 if available else None}}
    return capabilities


def _plan_with_capabilities(tmp_path, sample_video, monkeypatch, capabilities):
    monkeypatch.setattr("mcp_video.rescue.planner.snapshot_capabilities", lambda: capabilities)
    monkeypatch.setattr("mcp_video.rescue.renderer.snapshot_capabilities", lambda: capabilities)
    return _planned_fixture(tmp_path, sample_video)


def _subtitle_stream_count(path) -> int:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return len(json.loads(result.stdout).get("streams", []))


def _install_fake_local_whisper(tmp_path, monkeypatch):
    model_path = tmp_path / "cache" / "base.pt"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"verified local whisper model")
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    fake_whisper = SimpleNamespace(_MODELS={"base": f"https://models.invalid/{digest}/base.pt"})
    monkeypatch.setitem(sys.modules, "whisper", fake_whisper)
    monkeypatch.setattr("mcp_video.rescue.renderer.whisper_model_path", lambda model="base": model_path)
    return model_path, digest


def _add_safe_metadata_repair(plan_path):
    plan = RescuePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    evidence = [
        Metric(
            name="metadata_state",
            value=True,
            unit="boolean",
            definition="Fixture repair evidence.",
        )
    ]
    finding = Finding(
        id="metadata:normalize",
        type="metadata",
        summary="Container metadata needs normalization.",
        confidence=1.0,
        confidence_rationale="Renderer resume fixture.",
        evidence=evidence,
        parameters={},
        expected_benefit="Normalize the container through a bounded adapter.",
        tradeoffs=["Media is re-encoded."],
        executor="ffmpeg.normalize",
    )
    repair = Repair(
        id="metadata:normalize",
        type="metadata",
        disposition=Disposition.SAFE_REPAIR,
        confidence=1.0,
        confidence_rationale="Renderer resume fixture.",
        evidence=evidence,
        parameters={},
        expected_benefit="Normalize the container through a bounded adapter.",
        tradeoffs=["Media is re-encoded."],
        executor="ffmpeg.normalize",
        promotable=True,
    )
    plan = plan.model_copy(
        update={
            "findings": [*plan.findings, finding],
            "safe_repairs": [*plan.safe_repairs, repair],
            "plan_sha256": None,
        }
    )
    digest = "sha256:" + hashlib.sha256(canonical_payload(plan)).hexdigest()
    plan = plan.model_copy(update={"plan_sha256": digest})
    plan_path.write_text(json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return repair.id


def test_renderer_executes_only_approved_safe_repairs(tmp_path, sample_video):
    _, plan_path, plan = _planned_fixture(tmp_path, sample_video)
    safe = [repair["id"] for repair in plan["safe_repairs"]]

    receipt = render_rescue(str(plan_path), approved_repair_ids=safe[:1])

    assert receipt["approved_repair_ids"] == safe[:1]
    assert set(receipt["applied_repair_ids"]) <= set(safe[:1])
    assert receipt["status"] == "completed"
    assert receipt["package"]["promoted"] is True
    package = plan_path.parent / receipt["package"]["path"]
    inspected = inspect_rescue(str(package / "rescue-receipt.json"))
    assert inspected["integrity"]["all_present"] is True
    assert inspected["integrity"]["all_matching"] is True


def test_completed_receipt_points_to_hashed_packaged_receipt(tmp_path, sample_video):
    _, plan_path, _ = _planned_fixture(tmp_path, sample_video)

    receipt = render_rescue(str(plan_path), approved_repair_ids=[])

    packaged_receipt = plan_path.parent / receipt["receipt_path"]
    packaged_payload = json.loads(packaged_receipt.read_text(encoding="utf-8"))
    receipt_artifact = next(
        artifact for artifact in packaged_payload["package"]["artifacts"] if artifact["kind"] == "receipt"
    )
    assert packaged_receipt.name == "rescue-receipt.json"
    assert packaged_payload["receipt_path"] == receipt["receipt_path"]
    assert packaged_payload["receipt_sha256"] == receipt["receipt_sha256"]
    assert receipt_artifact["path"] == "rescue-receipt.json"
    assert receipt_artifact["sha256"] == receipt["receipt_sha256"]
    assert inspect_rescue(str(packaged_receipt))["integrity"]["all_matching"] is True

    packaged_payload["warnings"].append("tampered after promotion")
    packaged_receipt.write_text(json.dumps(packaged_payload), encoding="utf-8")
    assert inspect_rescue(str(packaged_receipt))["integrity"]["all_matching"] is False


def test_renderer_fails_closed_when_source_changes(tmp_path, sample_video):
    source, plan_path, _ = _planned_fixture(tmp_path, sample_video)
    source.write_bytes(source.read_bytes() + b"changed")

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path))

    assert caught.value.code == "rescue_source_mismatch"


def test_renderer_rejects_unknown_approval(tmp_path, sample_video):
    _, plan_path, _ = _planned_fixture(tmp_path, sample_video)

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), approved_repair_ids=["stabilization:crop"])

    assert caught.value.code == "rescue_approval_invalid"


def test_missing_whisper_records_unavailable_sidecars_without_transcribing(tmp_path, sample_video, monkeypatch):
    capabilities = _caption_capabilities(available=False)
    _, plan_path, plan = _plan_with_capabilities(tmp_path, sample_video, monkeypatch, capabilities)
    monkeypatch.setattr(
        "mcp_video.rescue.renderer.ai_transcribe",
        lambda *args, **kwargs: pytest.fail("unavailable Whisper must not be invoked"),
    )

    receipt = render_rescue(str(plan_path))

    intents = {item["kind"]: item for item in plan["package_intents"]}
    artifacts = {item["kind"]: item for item in receipt["package"]["artifacts"]}
    assert intents["captions"]["reason"] == "missing_local_whisper"
    assert artifacts["captions"] == {
        "kind": "captions",
        "status": "unavailable",
        "path": None,
        "sha256": None,
        "size_bytes": None,
        "reason": "missing_local_whisper",
    }
    assert artifacts["transcript"]["reason"] == "missing_local_whisper"
    assert receipt["status"] == "completed"


def test_local_whisper_writes_verified_sidecars_without_burning_them(tmp_path, sample_video, monkeypatch):
    model_path, digest = _install_fake_local_whisper(tmp_path, monkeypatch)
    capabilities = _caption_capabilities(
        available=True,
        model_sha256="sha256:" + digest,
    )
    _, plan_path, _ = _plan_with_capabilities(tmp_path, sample_video, monkeypatch, capabilities)

    def fake_transcribe(video, output_srt, model="base", language=None):
        assert model == "base"
        assert language is None
        with open(output_srt, "w", encoding="utf-8") as handle:
            handle.write("1\n00:00:00,000 --> 00:00:01,000\nhello\n")
        return {"transcript": "hello", "segments": [], "language": "en"}

    monkeypatch.setattr("mcp_video.rescue.renderer.ai_transcribe", fake_transcribe)

    receipt = render_rescue(str(plan_path))

    artifacts = {item["kind"]: item for item in receipt["package"]["artifacts"]}
    package = plan_path.parent / receipt["package"]["path"]
    operation = next(item for item in receipt["operations"] if item["id"] == "captions_transcript:package")
    assert artifacts["captions"]["path"] == "captions.srt"
    assert artifacts["transcript"]["path"] == "transcript.txt"
    assert operation["executor_version"] == "20250625"
    assert operation["parameters"]["model_sha256"] == "sha256:" + digest
    assert model_path.is_file()
    master = package / artifacts["master"]["path"]
    assert _subtitle_stream_count(master) == 0


def test_runtime_missing_whisper_is_nonfatal_and_explicit(tmp_path, sample_video, monkeypatch):
    _, digest = _install_fake_local_whisper(tmp_path, monkeypatch)
    capabilities = _caption_capabilities(available=True, model_sha256="sha256:" + digest)
    _, plan_path, _ = _plan_with_capabilities(tmp_path, sample_video, monkeypatch, capabilities)

    def missing(*args, **kwargs):
        raise MCPVideoError("missing", error_type="dependency_error", code="missing_whisper")

    monkeypatch.setattr("mcp_video.rescue.renderer.ai_transcribe", missing)

    receipt = render_rescue(str(plan_path))

    artifacts = {item["kind"]: item for item in receipt["package"]["artifacts"]}
    assert receipt["status"] == "completed"
    assert artifacts["captions"]["reason"] == "missing_whisper"
    assert artifacts["transcript"]["reason"] == "missing_whisper"


def test_whisper_import_disappearing_after_plan_is_nonfatal(tmp_path, sample_video, monkeypatch):
    model_path = tmp_path / "cache" / "base.pt"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"planned local model")
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    capabilities = _caption_capabilities(available=True, model_sha256="sha256:" + digest)
    _, plan_path, _ = _plan_with_capabilities(tmp_path, sample_video, monkeypatch, capabilities)
    monkeypatch.setattr("mcp_video.rescue.renderer.whisper_model_path", lambda model="base": model_path)
    original_import = builtins.__import__

    def import_without_whisper(name, *args, **kwargs):
        if name == "whisper":
            raise ImportError("Whisper removed after planning")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_whisper)

    receipt = render_rescue(str(plan_path))

    artifacts = {item["kind"]: item for item in receipt["package"]["artifacts"]}
    assert receipt["status"] == "completed"
    assert artifacts["captions"]["reason"] == "missing_whisper"


def test_transcription_execution_failure_quarantines_package(tmp_path, sample_video, monkeypatch):
    _, digest = _install_fake_local_whisper(tmp_path, monkeypatch)
    capabilities = _caption_capabilities(available=True, model_sha256="sha256:" + digest)
    _, plan_path, _ = _plan_with_capabilities(tmp_path, sample_video, monkeypatch, capabilities)
    receipt_path = plan_path.parent / "transcription-failed.json"

    def fail(*args, **kwargs):
        raise MCPVideoError("decode failed", error_type="processing_error", code="transcription_failed")

    monkeypatch.setattr("mcp_video.rescue.renderer.ai_transcribe", fail)

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), save_receipt=str(receipt_path))

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert caught.value.code == "rescue_verification_failed"
    assert receipt["status"] == "quarantined"
    assert receipt["package"]["promoted"] is False
    assert any(check["id"] == "caption_generation" and not check["passed"] for check in receipt["verification"])


def test_unexpected_caption_failure_is_sanitized_and_quarantines_package(tmp_path, sample_video, monkeypatch):
    _, digest = _install_fake_local_whisper(tmp_path, monkeypatch)
    capabilities = _caption_capabilities(available=True, model_sha256="sha256:" + digest)
    _, plan_path, _ = _plan_with_capabilities(tmp_path, sample_video, monkeypatch, capabilities)
    receipt_path = plan_path.parent / "unexpected-caption-failure.json"
    private_path = tmp_path / "captions.txt"

    def fail(*args, **kwargs):
        raise RuntimeError(f"private failure at {private_path}")

    monkeypatch.setattr("mcp_video.rescue.renderer.ai_transcribe", fail)

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), save_receipt=str(receipt_path))

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    check = next(item for item in receipt["verification"] if item["id"] == "caption_generation")
    assert caught.value.code == "rescue_verification_failed"
    assert receipt["status"] == "quarantined"
    assert check["details"] == {
        "error_code": "caption_generation_failed",
        "exception_type": "RuntimeError",
    }
    assert str(private_path) not in json.dumps(receipt)


def test_cancel_marker_prevents_promotion_and_records_receipt(tmp_path, sample_video):
    _, plan_path, _ = _planned_fixture(tmp_path, sample_video)
    cancel = tmp_path / "cancel"
    cancel.write_text("stop", encoding="utf-8")
    receipt = tmp_path / "output" / "cancelled.json"

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), save_receipt=str(receipt), cancel_file=str(cancel))

    assert caught.value.code == "rescue_cancelled"
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "cancelled"
    assert not [path for path in (tmp_path / "output").glob("*-rescue-*") if path.is_dir()]


def test_verification_failure_quarantines_without_success_status(tmp_path, sample_video, monkeypatch):
    _, plan_path, _ = _planned_fixture(tmp_path, sample_video)
    monkeypatch.setattr(
        "mcp_video.rescue.renderer.verify_package",
        lambda *args, **kwargs: [VerificationCheck(id="forced_failure", passed=False, message="Forced failure.")],
    )
    receipt_path = tmp_path / "output" / "failed.json"

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), save_receipt=str(receipt_path))

    assert caught.value.code == "rescue_verification_failed"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "quarantined"
    assert receipt["package"]["promoted"] is False
    assert (tmp_path / "output" / receipt["package"]["quarantine_path"]).is_dir()


def _cancel_after_first_repair(tmp_path, sample_video, monkeypatch):
    _, plan_path, _ = _planned_fixture(tmp_path, sample_video)
    repair_id = _add_safe_metadata_repair(plan_path)
    cancel = tmp_path / "cancel"
    receipt = tmp_path / "output" / "cancelled-after-repair.json"
    from mcp_video.rescue import renderer

    original = renderer.execute_repair

    def execute_then_cancel(*args, **kwargs):
        result = original(*args, **kwargs)
        cancel.write_text("stop", encoding="utf-8")
        return result

    monkeypatch.setattr(renderer, "execute_repair", execute_then_cancel)
    with pytest.raises(MCPVideoError):
        render_rescue(str(plan_path), save_receipt=str(receipt), cancel_file=str(cancel))
    return plan_path, receipt, repair_id


def test_resume_reuses_matching_completed_repair(tmp_path, sample_video, monkeypatch):
    plan_path, receipt_path, repair_id = _cancel_after_first_repair(tmp_path, sample_video, monkeypatch)
    monkeypatch.undo()
    calls: list[str] = []
    from mcp_video.rescue import renderer

    original = renderer.execute_repair
    monkeypatch.setattr(
        renderer, "execute_repair", lambda repair, *a, **k: calls.append(repair.id) or original(repair, *a, **k)
    )

    receipt = render_rescue(str(plan_path), resume_receipt=str(receipt_path))

    assert repair_id not in calls
    assert receipt["resume"]["used"] is True


def test_resume_rejects_tampered_intermediate(tmp_path, sample_video, monkeypatch):
    plan_path, receipt_path, _ = _cancel_after_first_repair(tmp_path, sample_video, monkeypatch)
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    intermediate = tmp_path / payload["operations"][0]["output_path"]
    intermediate.write_bytes(b"tampered")

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(str(plan_path), resume_receipt=str(receipt_path))

    assert caught.value.code == "rescue_intermediate_mismatch"
