"""Regression tests for Kinocut Chrome Native Messaging host and installer."""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import kinocut
from kinocut.errors import MCPVideoError
from kinocut.native_messaging import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    dispatch_message,
    read_frame,
    write_frame,
)
from kinocut.native_messaging_install import (
    NATIVE_HOST_NAME,
    default_manifest_dir,
    install_native_host,
    uninstall_native_host,
    validate_extension_id,
)

VALID_EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"


def _encode_frame(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return struct.pack("<I", len(body)) + body


def _make_synthetic_mp4(path: Path) -> str:
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg not installed")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=24",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return str(path)


def _run_host_session(messages: list[dict[str, Any]], *, env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    raw_in = b"".join(_encode_frame(msg) for msg in messages)
    proc = subprocess.run(
        [sys.executable, "-m", "kinocut.native_messaging"],
        input=raw_in,
        capture_output=True,
        timeout=120,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    stream = io.BytesIO(proc.stdout)
    responses: list[dict[str, Any]] = []
    while True:
        frame = read_frame(stream)
        if frame is None:
            break
        responses.append(frame)
    return responses


def test_binary_frame_roundtrip_and_eof() -> None:
    buf = io.BytesIO()
    first = {"action": "ping", "id": 1}
    second = {"action": "doctor", "id": "req-2"}
    write_frame(buf, first)
    write_frame(buf, second)

    buf.seek(0)
    assert read_frame(buf) == first
    assert read_frame(buf) == second
    assert read_frame(buf) is None


def test_read_frame_rejects_oversized_frame() -> None:
    oversized_header = struct.pack("<I", MAX_MESSAGE_BYTES + 1)
    with pytest.raises(MCPVideoError) as exc_info:
        read_frame(io.BytesIO(oversized_header + b"{}"))
    assert exc_info.value.code == "frame_too_large"


def test_write_frame_rejects_oversized_payload() -> None:
    huge = {"data": "x" * (MAX_MESSAGE_BYTES + 16)}
    with pytest.raises(MCPVideoError) as exc_info:
        write_frame(io.BytesIO(), huge)
    assert exc_info.value.code == "frame_too_large"


@pytest.mark.parametrize(
    ("raw", "expected_code"),
    [
        (b"\x01\x02", "truncated_frame"),
        (struct.pack("<I", 0), "empty_frame"),
        (struct.pack("<I", 20) + b'{"a":1}', "truncated_frame"),
        (struct.pack("<I", 2) + b"\xff\xfe", "invalid_utf8"),
        (struct.pack("<I", 7) + b"{broken", "invalid_json"),
        (struct.pack("<I", 7) + b"[1,2,3]", "invalid_payload"),
    ],
)
def test_read_frame_fails_closed_on_malformed_frames(raw: bytes, expected_code: str) -> None:
    with pytest.raises(MCPVideoError) as exc_info:
        read_frame(io.BytesIO(raw))
    assert exc_info.value.code == expected_code


def test_unknown_action_fails_closed_without_echoing_caller_string() -> None:
    unknown_action = "exec_unknown_op_9f3a7c"
    response = dispatch_message({"action": unknown_action, "id": "bad-1"})
    assert response["success"] is False
    assert response["id"] == "bad-1"
    assert response["error"]["code"] == "unsupported_action"
    assert "9f3a7c" not in json.dumps(response)


def test_subprocess_e2e_ping_doctor_info_quality_direct_and_review_card(tmp_path: Path) -> None:
    clip = _make_synthetic_mp4(tmp_path / "synthetic_clip.mp4")
    direct_out = str(tmp_path / "edited_direct.mp4")
    card_out = str(tmp_path / "clip_review_card.html")

    # Phase 1: read-only actions + direct_plan + unknown action in a single stdio session.
    phase1 = _run_host_session(
        [
            {"action": "ping", "id": "p1"},
            {"action": "doctor", "id": "p2"},
            {"action": "info", "params": {"input_path": clip}, "id": "p3"},
            {
                "action": "quality_check",
                "params": {"input_path": clip, "profile": "dark-grade"},
                "id": "p4",
            },
            {
                "action": "direct_plan",
                "params": {
                    "input_path": clip,
                    "direction": "cut to 1 second",
                    "output_path": direct_out,
                },
                "id": "p5",
            },
            {"action": "totally_unknown_leaked_42ab99", "id": "p6"},
        ]
    )

    assert len(phase1) == 6
    ping_res, doc_res, info_res, qc_res, plan_res, unknown_res = phase1

    assert ping_res["success"] is True
    assert ping_res["version"] == kinocut.__version__
    assert ping_res["protocol"] == PROTOCOL_VERSION
    assert isinstance(ping_res["offline"], bool)

    assert doc_res["success"] is True
    assert doc_res["required_ok"] is True
    assert doc_res["ffmpeg"]["ok"] is True
    assert "offline_readiness" in doc_res
    assert str(Path.home()) not in json.dumps(doc_res)

    assert info_res["success"] is True
    assert info_res["info"]["width"] == 320
    assert info_res["info"]["height"] == 240
    assert info_res["info"]["duration"] > 1.0

    assert qc_res["success"] is True
    assert qc_res["profile"] == "dark-grade"
    assert isinstance(qc_res["overall_score"], (int, float))
    assert qc_res["report"]["profile"]["name"] == "dark-grade"

    assert plan_res["success"] is True
    assert isinstance(plan_res["plan"], dict)
    assert len(plan_res["plan"]["steps"]) >= 1
    assert not Path(direct_out).exists()

    assert unknown_res["success"] is False
    assert unknown_res["error"]["code"] == "unsupported_action"
    assert "42ab99" not in json.dumps(unknown_res)

    # Phase 2: direct_apply confirmation gate, unresolved question refusal, real render, and review_card.
    plan = plan_res["plan"]
    plan_with_question = {**plan, "question": "Which resolution should be used?"}
    phase2 = _run_host_session(
        [
            {"action": "direct_apply", "params": {"plan": plan}, "id": "a1"},
            {"action": "direct_apply", "params": {"plan": plan, "confirm": False}, "id": "a2"},
            {"action": "direct_apply", "params": {"plan": plan, "confirm": "true"}, "id": "a3"},
            {
                "action": "direct_apply",
                "params": {"plan": plan_with_question, "confirm": True},
                "id": "a4",
            },
            {
                "action": "direct_apply",
                "params": {"plan": plan, "confirm": True, "overwrite": False},
                "id": "a5",
            },
            {
                "action": "review_card",
                "params": {"input_path": clip, "output_path": card_out, "overwrite": False},
                "id": "a6",
            },
        ]
    )

    assert len(phase2) == 6
    no_confirm, false_confirm, str_confirm, unresolved_res, applied_res, card_res = phase2

    assert no_confirm["success"] is False
    assert no_confirm["error"]["code"] == "confirmation_required"
    assert false_confirm["success"] is False
    assert false_confirm["error"]["code"] == "confirmation_required"
    assert str_confirm["success"] is False
    assert str_confirm["error"]["code"] == "confirmation_required"

    assert unresolved_res["success"] is False
    assert unresolved_res["error"]["code"] == "unresolved_direct_question"

    assert applied_res["success"] is True
    assert applied_res["dry_run"] is False
    assert Path(direct_out).is_file()

    assert card_res["success"] is True
    assert Path(card_out).is_file()
    assert card_res["approval_digest"].startswith("sha256:")
    assert len(card_res["input_sha256"]) == 64


def test_direct_apply_respects_overwrite_false_on_existing_output(tmp_path: Path) -> None:
    clip = _make_synthetic_mp4(tmp_path / "src.mp4")
    existing = tmp_path / "existing_direct.mp4"
    existing.write_bytes(b"original-content")

    plan_res = dispatch_message(
        {
            "action": "direct_plan",
            "params": {
                "input_path": clip,
                "direction": "cut to 1 second",
                "output_path": str(existing),
            },
        }
    )
    assert plan_res["success"] is True
    assert len(plan_res["plan"]["steps"]) >= 1

    refused = dispatch_message(
        {
            "action": "direct_apply",
            "params": {"plan": plan_res["plan"], "confirm": True, "overwrite": False},
        }
    )
    assert refused["success"] is False
    assert existing.read_bytes() == b"original-content"


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "shortid",
        "A" * 32,
        "q" * 32,
        "1" * 32,
        "a" * 31,
        "a" * 33,
        "../" + "a" * 29,
        "secret_ext_token_9f3a7c_zzzzzzzz",
    ],
)
def test_validate_extension_id_rejects_invalid_ids_without_echoing(bad_id: str) -> None:
    with pytest.raises(MCPVideoError) as exc_info:
        validate_extension_id(bad_id)
    assert exc_info.value.code == "invalid_extension_id"
    if len(bad_id) > 3:
        assert bad_id not in str(exc_info.value)


def test_install_and_uninstall_native_host_posix_and_windows(tmp_path: Path) -> None:
    posix_dir = tmp_path / "posix_hosts"
    installed = install_native_host(
        VALID_EXTENSION_ID,
        browser="chrome",
        target_dir=posix_dir,
        platform_name="linux",
    )
    manifest_path = Path(installed["manifest_path"])
    launcher_path = Path(installed["launcher_path"])

    assert installed["success"] is True
    assert manifest_path.is_file()
    assert manifest_path.name == f"{NATIVE_HOST_NAME}.json"
    assert launcher_path.is_file()
    assert launcher_path.name == "kinocut-native-host.sh"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == NATIVE_HOST_NAME
    assert manifest["type"] == "stdio"
    assert manifest["path"] == str(launcher_path.resolve())
    assert manifest["allowed_origins"] == [f"chrome-extension://{VALID_EXTENSION_ID}/"]

    launcher_text = launcher_path.read_text(encoding="utf-8")
    assert "-m kinocut.native_messaging" in launcher_text
    if os.name != "nt":
        assert bool(launcher_path.stat().st_mode & stat.S_IXUSR)

    removed = uninstall_native_host(browser="chrome", target_dir=posix_dir, platform_name="linux")
    assert removed["success"] is True
    assert removed["removed"] is True
    assert not manifest_path.exists()
    assert not launcher_path.exists()

    win_dir = tmp_path / "win_hosts"
    win_installed = install_native_host(
        VALID_EXTENSION_ID,
        browser="edge",
        target_dir=win_dir,
        platform_name="win32",
    )
    assert Path(win_installed["launcher_path"]).name == "kinocut-native-host.bat"
    assert "@echo off" in Path(win_installed["launcher_path"]).read_text(encoding="utf-8")


def test_default_manifest_dir_supports_linux_macos_and_windows(tmp_path: Path) -> None:
    linux_dir = default_manifest_dir("brave", platform_name="linux", home=tmp_path)
    mac_dir = default_manifest_dir("chrome", platform_name="darwin", home=tmp_path)
    win_dir = default_manifest_dir("chromium", platform_name="win32", home=tmp_path)

    assert "BraveSoftware" in str(linux_dir)
    assert "Google/Chrome/NativeMessagingHosts" in mac_dir.as_posix()
    assert "NativeMessagingHosts" in win_dir.as_posix()


def test_cli_install_and_uninstall_subprocess(tmp_path: Path) -> None:
    install_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut.native_messaging",
            "--install",
            "--extension-id",
            VALID_EXTENSION_ID,
            "--browser",
            "chromium",
            "--target-dir",
            str(tmp_path),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert install_proc.returncode == 0, install_proc.stderr
    payload = json.loads(install_proc.stdout)
    assert payload["success"] is True
    assert Path(payload["manifest_path"]).is_file()

    bad_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut.native_messaging",
            "--install",
            "--extension-id",
            "not-a-valid-extension-id-9f3a7c",
            "--target-dir",
            str(tmp_path),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert bad_proc.returncode == 2
    assert "9f3a7c" not in bad_proc.stderr

    uninstall_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "kinocut.native_messaging",
            "--uninstall",
            "--browser",
            "chromium",
            "--target-dir",
            str(tmp_path),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert uninstall_proc.returncode == 0, uninstall_proc.stderr
    uninstall_payload = json.loads(uninstall_proc.stdout)
    assert uninstall_payload["removed"] is True
    assert not (tmp_path / f"{NATIVE_HOST_NAME}.json").exists()
