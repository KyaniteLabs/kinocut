"""Native MCPB launcher must use only contained, target-matched runtimes."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    if sys.platform == "win32":
        pytest.skip("Windows native execution requires the dedicated clean-machine runner")
    target_os = "darwin" if sys.platform == "darwin" else "linux"
    target_arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64", "amd64": "x64"}[platform.machine().lower()]
    root = tmp_path / "bundle"
    (root / "server").mkdir(parents=True)
    shutil.copy2(Path(__file__).parents[1] / "mcpb/server/native-launcher.js", root / "server/native-launcher.js")
    (root / "runtime/node/bin").mkdir(parents=True)
    (root / "runtime/python/bin").mkdir(parents=True)
    (root / "runtime/ffmpeg/bin").mkdir(parents=True)
    (root / "runtime/runtime-metadata.json").write_text(
        json.dumps({"target": f"{target_os}-{target_arch}", "os": target_os, "arch": target_arch}),
        encoding="utf-8",
    )
    recorder = root / "runtime/python/bin/python3"
    recorder.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$KINOCUT_TEST_RECEIPT"\nprintf \'%s\\n\' "$PATH" >> "$KINOCUT_TEST_RECEIPT"\n',
        encoding="utf-8",
    )
    for path in [recorder, root / "runtime/ffmpeg/bin/ffmpeg", root / "runtime/ffmpeg/bin/ffprobe"]:
        if not path.exists():
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    return root


def test_native_launcher_uses_isolated_python_and_bundle_owned_path(bundle: Path, tmp_path: Path) -> None:
    receipt = tmp_path / "receipt"
    result = subprocess.run(
        ["node", str(bundle / "server/native-launcher.js")],
        env={**os.environ, "KINOCUT_TEST_RECEIPT": str(receipt)},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    lines = receipt.read_text(encoding="utf-8").splitlines()
    assert lines[:5] == ["-I", "-s", "-m", "kinocut", "--mcp"]
    assert lines[5].split(os.pathsep) == [
        str(bundle / "runtime/python/bin"),
        str(bundle / "runtime/ffmpeg/bin"),
        str(bundle / "runtime/node/bin"),
    ]


def test_native_launcher_rejects_target_mismatch(bundle: Path) -> None:
    (bundle / "runtime/runtime-metadata.json").write_text(
        json.dumps({"target": "windows-x64", "os": "windows", "arch": "x64"}), encoding="utf-8"
    )

    result = subprocess.run(
        ["node", str(bundle / "server/native-launcher.js")], capture_output=True, text=True, timeout=10
    )

    assert result.returncode == 126
    assert "does not match this host" in result.stderr


def test_native_launcher_rejects_runtime_symlink_escape(bundle: Path, tmp_path: Path) -> None:
    python = bundle / "runtime/python/bin/python3"
    python.unlink()
    outside = tmp_path / "outside-python"
    outside.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    outside.chmod(0o755)
    python.symlink_to(outside)

    result = subprocess.run(
        ["node", str(bundle / "server/native-launcher.js")], capture_output=True, text=True, timeout=10
    )

    assert result.returncode == 126
    assert "invalid bundled runtime" in result.stderr


def test_native_launcher_rejects_runtime_root_symlink_escape(bundle: Path, tmp_path: Path) -> None:
    runtime = bundle / "runtime"
    outside = tmp_path / "outside-runtime"
    runtime.rename(outside)
    runtime.symlink_to(outside, target_is_directory=True)

    result = subprocess.run(
        ["node", str(bundle / "server/native-launcher.js")], capture_output=True, text=True, timeout=10
    )

    assert result.returncode == 126
    assert "invalid bundled runtime" in result.stderr


def test_native_launcher_rejects_windows_cross_volume_paths() -> None:
    launcher = Path(__file__).parents[1] / "mcpb/server/native-launcher.js"
    script = (
        "const {isContainedPath}=require(process.argv[1]);"
        "const p=require('node:path').win32;"
        "process.exit(isContainedPath(p,'C:\\\\bundle\\\\runtime','D:\\\\outside\\\\python.exe')?1:0);"
    )

    result = subprocess.run(["node", "-e", script, str(launcher)], capture_output=True, text=True, timeout=10)

    assert result.returncode == 0, result.stderr
