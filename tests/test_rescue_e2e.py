"""Release-level end-to-end tests for the dedicated rescue pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import resource
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.rescue import inspect_rescue, plan_rescue, render_rescue
from tests.rescue_fixtures import (
    make_corrupt_fixture,
    make_long_unicode_fixture,
    make_rescue_fixture,
    make_unsupported_codec_fixture,
)


def _sha256(path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _stream_contract(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return {
        "types": [stream.get("codec_type") for stream in payload.get("streams", [])],
        "codecs": [stream.get("codec_name") for stream in payload.get("streams", [])],
        "format": payload.get("format", {}).get("format_name"),
        "duration": float(payload.get("format", {}).get("duration", 0)),
    }


def _render_public(source: Path, output: Path, *, approvals=None):
    plan_path = output / "plan.json"
    plan = plan_rescue(str(source), str(output), str(plan_path))
    receipt = render_rescue(str(plan_path), approved_repair_ids=approvals)
    return plan, receipt, output / receipt["package"]["path"]


@pytest.mark.slow
def test_fix_this_clip_end_to_end(tmp_path):
    source = make_rescue_fixture(
        tmp_path,
        rotation=90,
        brightness=-0.18,
        volume_db=-18,
        noise=True,
    )
    source_hash = _sha256(source)
    output = tmp_path / "diagnosis"
    plan_path = output / "plan.json"

    plan = plan_rescue(str(source), str(output), str(plan_path))
    receipt = render_rescue(str(plan_path))
    package = output / receipt["package"]["path"]
    inspection = inspect_rescue(str(package / "rescue-receipt.json"))

    assert _sha256(source) == source_hash
    assert plan["status"] == "planned"
    assert receipt["status"] == "completed"
    assert {"master", "sharing_copy"} <= {
        artifact["kind"] for artifact in receipt["package"]["artifacts"] if artifact["status"] == "available"
    }
    assert inspection["integrity"]["all_matching"] is True
    assert all(check["passed"] for check in receipt["verification"] if check["gating"])


@pytest.mark.slow
@pytest.mark.parametrize("container", ["mov", "webm"])
def test_container_inputs_produce_verified_universal_package(tmp_path, container):
    source = make_rescue_fixture(tmp_path, container=container)

    _, receipt, package = _render_public(source, tmp_path / f"out-{container}", approvals=[])

    artifacts = {item["kind"]: item for item in receipt["package"]["artifacts"]}
    sharing = _stream_contract(package / artifacts["sharing_copy"]["path"])
    assert receipt["status"] == "completed"
    assert "h264" in sharing["codecs"]
    assert "mp4" in sharing["format"]


@pytest.mark.slow
def test_unicode_long_name_remains_confined_and_inspectable(tmp_path):
    source = make_long_unicode_fixture(tmp_path)
    source_hash = _sha256(source)

    _, _, package = _render_public(source, tmp_path / "unicode-output", approvals=[])
    inspection = inspect_rescue(str(package / "rescue-receipt.json"))

    assert _sha256(source) == source_hash
    assert inspection["integrity"]["all_matching"] is True
    assert package.parent == tmp_path / "unicode-output"


@pytest.mark.slow
@pytest.mark.parametrize(
    "defects",
    [
        {"vfr": True},
        {"drift_ms": 180},
        {"volume_db": 18},
        {"noise": True},
        {"brightness": -0.2},
    ],
)
def test_timeline_and_quality_defects_never_escape_policy(tmp_path, defects):
    source = make_rescue_fixture(tmp_path, **defects)
    source_hash = _sha256(source)

    plan, receipt, _ = _render_public(source, tmp_path / "policy-output", approvals=[])

    safe_types = {repair["type"] for repair in plan["safe_repairs"]}
    assert not safe_types.intersection(
        {"stabilization", "reframe", "timeline_edit", "synthetic_content", "cloud_processing"}
    )
    assert receipt["applied_repair_ids"] == []
    assert receipt["status"] == "completed"
    assert _sha256(source) == source_hash


@pytest.mark.parametrize("builder", [make_corrupt_fixture, make_unsupported_codec_fixture])
def test_invalid_media_fails_closed_without_promoted_package(tmp_path, builder):
    source = builder(tmp_path)
    output = tmp_path / "invalid-output"

    with pytest.raises(MCPVideoError) as caught:
        plan_rescue(str(source), str(output), str(output / "plan.json"))

    assert caught.value.code == "invalid_rescue_input"
    assert not output.exists() or not list(output.glob("*-rescue-*"))


def test_symlink_source_escape_is_rejected_at_command_entry(tmp_path):
    outside_root = tmp_path.parent / f"outside-{tmp_path.name}"
    source = make_rescue_fixture(outside_root)
    link = tmp_path / "linked-source.mp4"
    link.symlink_to(source)

    with pytest.raises(MCPVideoError) as caught:
        plan_rescue(str(link), str(tmp_path / "output"))

    assert caught.value.code == "unsafe_rescue_output"
    assert not (tmp_path / "output").exists()


@pytest.mark.slow
def test_rescue_uses_no_network_and_preserves_source(tmp_path, monkeypatch):
    source = make_rescue_fixture(tmp_path)
    source_hash = _sha256(source)

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("rescue pipeline attempted network access"),
    )
    _, receipt, _ = _render_public(source, tmp_path / "local-output", approvals=[])

    assert receipt["privacy"] == {
        "local_only": True,
        "network_used": False,
        "source_overwritten": False,
    }
    assert _sha256(source) == source_hash


@pytest.mark.slow
def test_cancelled_render_resumes_through_public_contract(tmp_path):
    source = make_rescue_fixture(tmp_path)
    output = tmp_path / "resume-output"
    plan_path = output / "plan.json"
    receipt_path = output / "cancelled.json"
    cancel_file = tmp_path / "cancel"
    plan_rescue(str(source), str(output), str(plan_path))
    cancel_file.write_text("cancel", encoding="utf-8")

    with pytest.raises(MCPVideoError) as caught:
        render_rescue(
            str(plan_path),
            approved_repair_ids=[],
            save_receipt=str(receipt_path),
            cancel_file=str(cancel_file),
        )
    assert caught.value.code == "rescue_cancelled"
    cancel_file.unlink()

    receipt = render_rescue(
        str(plan_path),
        approved_repair_ids=[],
        resume_receipt=str(receipt_path),
    )

    assert receipt["status"] == "completed"
    assert receipt["resume"]["used"] is True


@pytest.mark.slow
def test_plan_and_render_semantics_are_reproducible(tmp_path):
    source = make_rescue_fixture(tmp_path)
    first_output = tmp_path / "first"
    first_path = first_output / "plan.json"
    first = plan_rescue(str(source), str(first_output), str(first_path))
    repeated = plan_rescue(str(source), str(first_output), str(first_output / "repeat.json"))
    second_output = tmp_path / "second"
    second_path = second_output / "plan.json"
    plan_rescue(str(source), str(second_output), str(second_path))

    first_receipt = render_rescue(str(first_path), approved_repair_ids=[])
    second_receipt = render_rescue(str(second_path), approved_repair_ids=[])
    first_package = first_output / first_receipt["package"]["path"]
    second_package = second_output / second_receipt["package"]["path"]
    first_artifacts = {item["kind"]: item for item in first_receipt["package"]["artifacts"]}
    second_artifacts = {item["kind"]: item for item in second_receipt["package"]["artifacts"]}

    assert first["plan_sha256"] == repeated["plan_sha256"]
    assert set(first_artifacts) == set(second_artifacts)
    for kind in ("master", "sharing_copy"):
        first_contract = _stream_contract(first_package / first_artifacts[kind]["path"])
        second_contract = _stream_contract(second_package / second_artifacts[kind]["path"])
        assert first_contract["types"] == second_contract["types"]
        assert first_contract["codecs"] == second_contract["codecs"]
        assert abs(first_contract["duration"] - second_contract["duration"]) <= 0.1
    assert [item["id"] for item in first_receipt["verification"]] == [
        item["id"] for item in second_receipt["verification"]
    ]


@pytest.mark.slow
def test_planning_performance_receipt_has_required_context(tmp_path, capsys):
    source = tmp_path / "performance-source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x727272:size=1920x1080:rate=30:duration=60",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000:duration=60",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        timeout=120,
    )
    timings = []
    plans = []
    for name in ("cold", "warm"):
        started = time.monotonic()
        plan = plan_rescue(str(source), str(tmp_path / "performance"), str(tmp_path / "performance" / f"{name}.json"))
        timings.append(time.monotonic() - started)
        plans.append(plan)
    ffmpeg_version = subprocess.run(
        ["ffmpeg", "-version"], check=True, capture_output=True, text=True
    ).stdout.splitlines()[0]
    report = {
        "cold_seconds": timings[0],
        "warm_seconds": timings[1],
        "cpu": platform.processor() or "unknown",
        "memory_max_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "os": platform.platform(),
        "ffmpeg_version": ffmpeg_version,
        "clip": {"duration_seconds": 60, "width": 1920, "height": 1080, "fps": 30},
        "enabled_analyzers": ["brightness", "audio_levels", "color_balance"],
        "sample_limit": 120,
        "local_model_available": plans[0]["capabilities"]["whisper_models"]["base"]["available"],
        "predicted_seconds": plans[0]["estimate"]["seconds"],
        "actual_seconds": plans[0]["observed_planning_seconds"],
        "absolute_estimate_error": abs(plans[0]["estimate"]["seconds"] - plans[0]["observed_planning_seconds"]),
        "target_seconds": 30,
    }
    report_path = tmp_path / "rescue-planning-performance.json"
    serialized_report = json.dumps(report, indent=2, sort_keys=True) + "\n"
    report_path.write_text(serialized_report, encoding="utf-8")
    if capture_path := os.environ.get("MCP_VIDEO_RESCUE_PERF_REPORT"):
        durable_report = Path(capture_path)
        durable_report.parent.mkdir(parents=True, exist_ok=True)
        durable_report.write_text(serialized_report, encoding="utf-8")
    print(json.dumps({"performance_report": str(report_path), **report}, sort_keys=True))

    assert report_path.is_file()
    assert set(report) == {
        "cold_seconds",
        "warm_seconds",
        "cpu",
        "memory_max_rss",
        "os",
        "ffmpeg_version",
        "clip",
        "enabled_analyzers",
        "sample_limit",
        "local_model_available",
        "predicted_seconds",
        "actual_seconds",
        "absolute_estimate_error",
        "target_seconds",
    }
    assert report["sample_limit"] == 120
    assert "performance_report" in capsys.readouterr().out
