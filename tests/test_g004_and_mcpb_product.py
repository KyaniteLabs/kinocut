"""G004 synthetic fixture pack + fail-closed MCPB readiness receipt."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kinocut.watching import ReviewPolicy, run_review


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_g004_phone_frame_fixture_and_review(tmp_path: Path) -> None:
    out_dir = tmp_path / "g004"
    proc = subprocess.run(
        [sys.executable, "scripts/make_g004_fixtures.py", "--out-dir", str(out_dir), "--seconds", "6"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    phones = list(out_dir.glob("*.mp4"))
    assert phones, proc.stdout
    media = phones[0]
    assert media.stat().st_size > 1000
    assert run_review(str(media), ReviewPolicy()).to_dict()["artifact_kind"] == "review_run"
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_kind"] == "g004_fixture_pack"


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _base_receipts(tmp_path: Path) -> tuple[str, str, list[Path]]:
    source = "a" * 40
    digest = "b" * 64
    wheel_digest = "d" * 64
    receipts = [
        _write(
            tmp_path / "build.json",
            {
                "artifact_kind": "mcpb_build_receipt",
                "source_sha": source,
                "archive_sha256": digest,
                "archive_inventory": ["README.md", "manifest.json", "server/launcher.js"],
            },
        ),
        _write(
            tmp_path / "official.json",
            {
                "artifact_kind": "mcpb_official_validation",
                "source_sha": source,
                "archive_sha256": digest,
                "wheel_sha256": wheel_digest,
                "validator": {"name": "@anthropic-ai/mcpb", "version": "2.1.2"},
                "source_manifest": "passed",
                "extracted_manifest": "passed",
            },
        ),
    ]
    for os_name in ("linux", "macos", "windows"):
        receipts.append(
            _write(
                tmp_path / f"hosted-{os_name}.json",
                {
                    "artifact_kind": "mcpb_hosted_runtime",
                    "source_sha": source,
                    "archive_sha256": digest,
                    "wheel_sha256": wheel_digest,
                    "archive_inventory": ["README.md", "manifest.json", "server/launcher.js"],
                    "os": os_name,
                    "architecture": "X64",
                    "status": "passed",
                    "cleanup": "passed",
                    "gates": {
                        "initialize": "passed",
                        "list_tools": "passed",
                        "core_call": "passed",
                        "core_after_missing_whisper": "passed",
                        "missing_whisper": "passed",
                        "hyperframes_not_found": "passed",
                        "session_reuse": "passed",
                        "cleanup_probe": "passed",
                    },
                },
            )
        )
    receipts.append(
        _write(
            tmp_path / "optional.json",
            {
                "artifact_kind": "mcpb_optional_dependencies",
                "source_sha": source,
                "archive_sha256": digest,
                "wheel_sha256": wheel_digest,
                "archive_inventory": ["README.md", "manifest.json", "server/launcher.js"],
                "os": "linux",
                "architecture": "X64",
                "status": "passed",
                "cleanup": "passed",
                "gates": {
                    "imagehash_detected": "passed",
                    "hyperframes_0_8_30_detected": "passed",
                    "scene_tool_callable": "passed",
                },
                "imagehash_detected": "passed",
                "hyperframes_0_8_30_detected": "passed",
                "scene_tool_callable": "passed",
            },
        )
    )
    return source, digest, receipts


def _run_pack(
    tmp_path: Path, receipts: list[Path], *extra: str, source_sha: str = "a" * 40
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "scripts/mcpb_production_pack.py",
        "--out-dir",
        str(tmp_path / "out"),
        "--source-sha",
        source_sha,
        "--build-receipt",
        str(receipts[0]),
        "--official-validation-receipt",
        str(receipts[1]),
    ]
    for receipt in receipts[2:5]:
        command.extend(["--hosted-runtime-receipt", str(receipt)])
    command.extend(["--optional-dependencies-receipt", str(receipts[5]), *extra])
    return subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)


def test_mcpb_receipt_is_ci_validated_only_for_complete_exact_evidence(tmp_path: Path) -> None:
    _, digest, receipts = _base_receipts(tmp_path)

    proc = _run_pack(tmp_path, receipts, "--require-ready", "ci_validated")

    assert proc.returncode == 0, proc.stderr
    checklist = json.loads((tmp_path / "out" / "production-checklist.json").read_text(encoding="utf-8"))
    assert checklist["artifact"] == {"status": "built", "sha256": digest}
    assert checklist["official_validation"]["status"] == "passed"
    assert set(checklist["hosted_runtime"]) == {"linux", "macos", "windows"}
    assert checklist["candidate_status"] == "ci_validated"
    assert checklist["desktop_install_review"] == {}
    assert checklist["signing"]["status"] == "unsigned"
    assert checklist["publication"]["status"] == "not_attempted"


def test_mcpb_receipt_blocks_missing_or_mismatched_evidence(tmp_path: Path) -> None:
    _, _, receipts = _base_receipts(tmp_path)
    payload = json.loads(receipts[4].read_text(encoding="utf-8"))
    payload["archive_sha256"] = "c" * 64
    receipts[4].write_text(json.dumps(payload), encoding="utf-8")

    proc = _run_pack(tmp_path, receipts, "--require-ready", "ci_validated")

    assert proc.returncode != 0
    checklist = json.loads((tmp_path / "out" / "production-checklist.json").read_text(encoding="utf-8"))
    assert checklist["candidate_status"] == "blocked"
    assert checklist["hosted_runtime"]["windows"]["status"] == "failed"
    rendered = json.dumps(checklist)
    assert "unsigned_pack_ready" not in rendered
    assert "product-complete" not in rendered


def test_mcpb_receipt_blocks_runtime_from_a_different_wheel(tmp_path: Path) -> None:
    _, _, receipts = _base_receipts(tmp_path)
    payload = json.loads(receipts[2].read_text(encoding="utf-8"))
    payload["wheel_sha256"] = "e" * 64
    receipts[2].write_text(json.dumps(payload), encoding="utf-8")

    proc = _run_pack(tmp_path, receipts, "--require-ready", "ci_validated")

    assert proc.returncode != 0
    checklist = json.loads((tmp_path / "out" / "production-checklist.json").read_text(encoding="utf-8"))
    assert checklist["candidate_status"] == "blocked"
    assert checklist["hosted_runtime"]["linux"]["status"] == "failed"


def test_mcpb_receipt_blocks_runtime_without_observed_cleanup_probe(tmp_path: Path) -> None:
    _, _, receipts = _base_receipts(tmp_path)
    payload = json.loads(receipts[2].read_text(encoding="utf-8"))
    payload["gates"].pop("cleanup_probe")
    receipts[2].write_text(json.dumps(payload), encoding="utf-8")

    proc = _run_pack(tmp_path, receipts, "--require-ready", "ci_validated")

    assert proc.returncode != 0
    checklist = json.loads((tmp_path / "out" / "production-checklist.json").read_text(encoding="utf-8"))
    assert checklist["hosted_runtime"]["linux"]["status"] == "failed"


@pytest.mark.parametrize(
    ("kind", "malformed"),
    [("source", "x" * 40), ("archive", "z" * 64), ("wheel", "y" * 64), ("source", "A" * 40)],
)
def test_mcpb_receipt_rejects_noncanonical_identifiers(tmp_path: Path, kind: str, malformed: str) -> None:
    source, _, receipts = _base_receipts(tmp_path)
    if kind == "source":
        source = malformed
        for path in receipts:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_sha"] = malformed
            path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        field = f"{kind}_sha256"
        for path in receipts:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload[field] = malformed
            path.write_text(json.dumps(payload), encoding="utf-8")

    proc = _run_pack(tmp_path, receipts, "--require-ready", "ci_validated", source_sha=source)

    assert proc.returncode != 0
    checklist = json.loads((tmp_path / "out" / "production-checklist.json").read_text(encoding="utf-8"))
    assert checklist["candidate_status"] == "blocked"


def _desktop_receipt(tmp_path: Path, os_name: str, source: str, archive: str, wheel: str) -> Path:
    return _write(
        tmp_path / f"desktop-{os_name}.json",
        {
            "artifact_kind": "mcpb_desktop_install",
            "source_sha": source,
            "archive_sha256": archive,
            "wheel_sha256": wheel,
            "os": os_name,
            "architecture": "arm64" if os_name == "macos" else "X64",
            "status": "passed",
            "gates": {
                "wheel_import": "passed",
                "server_start": "passed",
                "mcp_round_trip": "passed",
                "unsigned_warning_observed": "passed",
                "local_access_label_reviewed": "passed",
            },
            "human_review": {
                "status": "passed",
                "reviewer": "release-reviewer",
                "reviewed_at": "2026-09-06T23:59:59Z",
            },
        },
    )


def test_mcpb_install_review_requires_two_complete_distinct_desktop_receipts(tmp_path: Path) -> None:
    source, archive, receipts = _base_receipts(tmp_path)
    wheel = json.loads(receipts[1].read_text(encoding="utf-8"))["wheel_sha256"]
    desktop = [_desktop_receipt(tmp_path, host, source, archive, wheel) for host in ("macos", "windows")]

    proc = _run_pack(
        tmp_path,
        receipts,
        "--desktop-install-receipt",
        str(desktop[0]),
        "--desktop-install-receipt",
        str(desktop[1]),
        "--require-ready",
        "install_reviewed",
    )

    assert proc.returncode == 0, proc.stderr
    checklist = json.loads((tmp_path / "out" / "production-checklist.json").read_text(encoding="utf-8"))
    assert checklist["candidate_status"] == "install_reviewed"
    assert checklist["human_review"]["status"] == "passed"
    assert checklist["desktop_install_review"]["macos"]["reviewer"] == "release-reviewer"
    assert checklist["desktop_install_review"]["windows"]["reviewed_at"] == "2026-09-06T23:59:59Z"


@pytest.mark.parametrize(
    "missing",
    [
        "wheel_sha256",
        "architecture",
        "wheel_import",
        "server_start",
        "mcp_round_trip",
        "unsigned_warning_observed",
        "local_access_label_reviewed",
        "reviewer",
        "reviewed_at",
    ],
)
def test_mcpb_install_review_rejects_each_missing_desktop_observation(tmp_path: Path, missing: str) -> None:
    source, archive, receipts = _base_receipts(tmp_path)
    wheel = json.loads(receipts[1].read_text(encoding="utf-8"))["wheel_sha256"]
    desktop = [_desktop_receipt(tmp_path, host, source, archive, wheel) for host in ("macos", "windows")]
    payload = json.loads(desktop[0].read_text(encoding="utf-8"))
    if missing in payload:
        payload.pop(missing)
    elif missing in payload["gates"]:
        payload["gates"].pop(missing)
    else:
        payload["human_review"].pop(missing)
    desktop[0].write_text(json.dumps(payload), encoding="utf-8")

    proc = _run_pack(
        tmp_path,
        receipts,
        "--desktop-install-receipt",
        str(desktop[0]),
        "--desktop-install-receipt",
        str(desktop[1]),
        "--require-ready",
        "install_reviewed",
    )

    assert proc.returncode != 0


def test_mcpb_install_review_rejects_duplicate_desktop_host(tmp_path: Path) -> None:
    source, archive, receipts = _base_receipts(tmp_path)
    wheel = json.loads(receipts[1].read_text(encoding="utf-8"))["wheel_sha256"]
    macos = _desktop_receipt(tmp_path, "macos", source, archive, wheel)

    proc = _run_pack(
        tmp_path,
        receipts,
        "--desktop-install-receipt",
        str(macos),
        "--desktop-install-receipt",
        str(macos),
        "--require-ready",
        "install_reviewed",
    )

    assert proc.returncode != 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha", "c" * 40),
        ("archive_sha256", "c" * 64),
        ("wheel_sha256", "e" * 64),
        ("os", "linux"),
        ("architecture", ""),
        ("status", "failed"),
        ("gates", {}),
        ("human_review", {"status": "not_run", "reviewer": "release-reviewer", "reviewed_at": "2026-09-06T23:59:59Z"}),
        ("human_review", {"status": "passed", "reviewer": "", "reviewed_at": "2026-09-06T23:59:59Z"}),
        ("human_review", {"status": "passed", "reviewer": "release-reviewer", "reviewed_at": "2026-99-99T23:59:59Z"}),
    ],
)
def test_mcpb_install_review_rejects_invalid_desktop_evidence(tmp_path: Path, field: str, value: object) -> None:
    source, archive, receipts = _base_receipts(tmp_path)
    wheel = json.loads(receipts[1].read_text(encoding="utf-8"))["wheel_sha256"]
    desktop = [_desktop_receipt(tmp_path, host, source, archive, wheel) for host in ("macos", "windows")]
    payload = json.loads(desktop[0].read_text(encoding="utf-8"))
    payload[field] = value
    desktop[0].write_text(json.dumps(payload), encoding="utf-8")

    proc = _run_pack(
        tmp_path,
        receipts,
        "--desktop-install-receipt",
        str(desktop[0]),
        "--desktop-install-receipt",
        str(desktop[1]),
        "--require-ready",
        "install_reviewed",
    )

    assert proc.returncode != 0


@pytest.mark.parametrize(
    "mutation",
    ["wrong_os", "missing_architecture", "blank_architecture", "missing_nested_gate", "wrong_wheel", "duplicate"],
)
def test_mcpb_optional_receipt_requires_one_complete_linux_row(tmp_path: Path, mutation: str) -> None:
    _, _, receipts = _base_receipts(tmp_path)
    payload = json.loads(receipts[5].read_text(encoding="utf-8"))
    if mutation == "wrong_os":
        payload["os"] = "wrong-host"
    elif mutation == "missing_architecture":
        payload.pop("architecture")
    elif mutation == "blank_architecture":
        payload["architecture"] = ""
    elif mutation == "missing_nested_gate":
        payload["gates"].pop("imagehash_detected")
    elif mutation == "wrong_wheel":
        payload["wheel_sha256"] = "e" * 64
    receipts[5].write_text(json.dumps(payload), encoding="utf-8")
    extra = ("--optional-dependencies-receipt", str(receipts[5])) if mutation == "duplicate" else ()

    proc = _run_pack(tmp_path, receipts, *extra, "--require-ready", "ci_validated")

    assert proc.returncode != 0


def test_mcpb_pack_without_receipts_is_blocked_and_skip_build_is_removed(tmp_path: Path) -> None:
    empty = subprocess.run(
        [sys.executable, "scripts/mcpb_production_pack.py", "--out-dir", str(tmp_path / "empty")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    skipped = subprocess.run(
        [sys.executable, "scripts/mcpb_production_pack.py", "--skip-build"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert empty.returncode == 0
    checklist = json.loads((tmp_path / "empty" / "production-checklist.json").read_text(encoding="utf-8"))
    assert checklist["artifact"] == {"status": "not_run", "sha256": None}
    assert checklist["candidate_status"] == "blocked"
    assert skipped.returncode != 0
