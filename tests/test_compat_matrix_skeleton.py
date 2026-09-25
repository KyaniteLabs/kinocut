"""Compat-matrix harness skeleton tests (COMPAT-MATRIX-SPEC build order 1).

Covers: the cli-ground-truth canonical run end-to-end with valid per-step
receipts; the append-only receipts law; receipt schema validation; and the
MCP client handshake with manifest-byte accounting.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "compat-matrix"))

from matrix_harness import main as harness_main  # noqa: E402
from receipt_writer import (  # noqa: E402
    REQUIRED_FIELDS,
    ReceiptWriter,
    detect_cloud_keys,
    validate_receipt,
)

STEP_COUNT = 6


def _run_harness(run_root: Path) -> int:
    return harness_main(["--run-root", str(run_root)])


def test_cli_ground_truth_run_end_to_end(tmp_path: Path) -> None:
    rc = _run_harness(tmp_path)
    assert rc == 0, "cli-ground-truth run must exit 0 (all wired steps pass)"
    run_dir = next(iter(tmp_path.iterdir()))  # the date-named run dir
    steps = [json.loads(line) for line in (run_dir / "steps.jsonl").read_text().splitlines()]
    assert len(steps) == STEP_COUNT
    by_step = {s["step"]: s for s in steps}
    assert list(by_step) == ["ingest", "trim", "caption", "repurpose", "quality-gate", "receipt"]
    for name in ("ingest", "trim", "repurpose", "quality-gate", "receipt"):
        assert by_step[name]["outcome"] == "pass", name
        assert by_step[name]["artifact_sha256"], f"{name} must hash a real artifact"
    # caption honestly not wired in the skeleton era — never faked
    assert by_step["caption"]["outcome"] == "not_wired"
    assert by_step["caption"]["fail_reason"] == "not_wired"
    for step in steps:
        assert not step["cloud_keys_present"]
        assert step["tokens"] == {"prompt": 0, "completion": 0, "manifest_bytes": 0}
    runs = [json.loads(line) for line in (run_dir / "runs.jsonl").read_text().splitlines()]
    assert runs[-1]["wired_pass_all"] is True
    assert runs[-1]["steps_not_wired"] == 1


def test_receipts_append_only_law(tmp_path: Path) -> None:
    assert _run_harness(tmp_path) == 0
    run_dir = next(iter(tmp_path.iterdir()))
    steps_path = run_dir / "steps.jsonl"
    first = steps_path.read_bytes()
    assert _run_harness(tmp_path) == 0  # second run, same dir
    second = steps_path.read_bytes()
    assert second.startswith(first), "history must never be rewritten"
    assert second.count(b"\n") == first.count(b"\n") + STEP_COUNT


def test_receipt_schema_validation() -> None:
    good = {
        "tier": "T2",
        "model": "llama-3-8b",
        "endpoint": "http://mini:8788/v1",
        "step": "trim",
        "attempt": 1,
        "tool_call": "video_trim",
        "tool_args_valid": True,
        "outcome": "pass",
        "fail_reason": None,
        "tokens": {"prompt": 10, "completion": 5, "manifest_bytes": 100},
        "latency_ms": 250,
        "artifact_sha256": "a" * 64,
        "ground_truth_diff": "identical",
        "cloud_keys_present": False,
        "timestamp_utc": "2026-09-25T00:00:00Z",
    }
    assert validate_receipt(good) == []
    missing = {k: v for k, v in good.items() if k != "tier"}
    assert "missing field: tier" in validate_receipt(missing)
    no_reason = dict(good, outcome="fail")
    assert any("fail_reason" in e for e in validate_receipt(no_reason))
    assert validate_receipt(dict(good, outcome="banana"))
    assert validate_receipt(dict(good, artifact_sha256="nothex"))


def test_cloud_key_detection_isolated() -> None:
    assert detect_cloud_keys({}) is False
    assert detect_cloud_keys({"PATH": "/bin", "HOME": "/tmp"}) is False
    assert detect_cloud_keys({"OPENAI_API_KEY": "x"}) is True
    assert detect_cloud_keys({"KINOCUT_VISION_API_KEY": "x"}) is True


def test_writer_rejects_invalid_receipt(tmp_path: Path) -> None:
    writer = ReceiptWriter(tmp_path)
    bad = dict.fromkeys(REQUIRED_FIELDS)
    with pytest.raises(ValueError):
        writer.write_step(bad)  # type: ignore[arg-type]
    assert not (tmp_path / "steps.jsonl").exists(), "rejected receipts must not touch the ledger"


def test_mcp_client_handshake_and_manifest() -> None:
    from mcp_client import MCPStdioClient

    with MCPStdioClient([sys.executable, "-m", "kinocut", "--mcp"], cwd=str(REPO_ROOT), timeout=90.0) as client:
        info = client.handshake()
    assert info.tools_count >= 100, "kinocut's MCP surface is ~196 tools"
    assert info.manifest_bytes > 10_000, "manifest byte accounting must produce a real number"
    assert info.server_name
