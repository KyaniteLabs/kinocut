"""Install and uninstall the Chrome Native Messaging host manifest for Kinocut."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any

from .errors import MCPVideoError

NATIVE_HOST_NAME = "tech.kyanitelabs.kinocut"
NATIVE_HOST_DESCRIPTION = "Kinocut local video editing Native Messaging host"
EXTENSION_ID_RE = re.compile(r"^[a-p]{32}$")
SUPPORTED_BROWSERS = ("chrome", "chromium", "brave", "edge")

_LINUX_BROWSER_DIRS = {
    "chrome": Path(".config/google-chrome/NativeMessagingHosts"),
    "chromium": Path(".config/chromium/NativeMessagingHosts"),
    "brave": Path(".config/BraveSoftware/Brave-Browser/NativeMessagingHosts"),
    "edge": Path(".config/microsoft-edge/NativeMessagingHosts"),
}

_MACOS_BROWSER_DIRS = {
    "chrome": Path("Library/Application Support/Google/Chrome/NativeMessagingHosts"),
    "chromium": Path("Library/Application Support/Chromium/NativeMessagingHosts"),
    "brave": Path("Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts"),
    "edge": Path("Library/Application Support/Microsoft Edge/NativeMessagingHosts"),
}


def validate_extension_id(extension_id: Any) -> str:
    """Strictly validate a Chrome extension ID (32 lowercase letters a-p)."""
    if not isinstance(extension_id, str) or EXTENSION_ID_RE.fullmatch(extension_id) is None:
        raise MCPVideoError(
            "extension_id must be a 32-character lowercase Chrome extension ID using only letters a-p.",
            error_type="validation_error",
            code="invalid_extension_id",
        )
    return extension_id


def validate_browser(browser: Any) -> str:
    """Validate the target Chromium-family browser identifier."""
    if not isinstance(browser, str):
        raise MCPVideoError(
            "browser must be one of chrome, chromium, brave, or edge.",
            error_type="validation_error",
            code="invalid_browser",
        )
    normalized = browser.strip().lower()
    if normalized not in SUPPORTED_BROWSERS:
        raise MCPVideoError(
            "browser must be one of chrome, chromium, brave, or edge.",
            error_type="validation_error",
            code="invalid_browser",
        )
    return normalized


def default_manifest_dir(
    browser: str = "chrome",
    *,
    platform_name: str | None = None,
    home: Path | None = None,
) -> Path:
    """Return the default OS-specific Native Messaging host manifest directory."""
    normalized = validate_browser(browser)
    plat = (platform_name or sys.platform).lower()
    base_home = (home or Path.home()).expanduser()
    if plat == "darwin":
        return base_home / _MACOS_BROWSER_DIRS[normalized]
    if plat.startswith("win"):
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else base_home / "AppData" / "Local"
        return base / "Kinocut" / "NativeMessagingHosts" / normalized
    return base_home / _LINUX_BROWSER_DIRS[normalized]


def _resolve_manifest_dir(
    browser: str,
    target_dir: str | Path | None,
    platform_name: str | None,
) -> Path:
    if target_dir is None:
        return default_manifest_dir(browser, platform_name=platform_name)
    text = str(target_dir)
    if not text.strip() or "\x00" in text:
        raise MCPVideoError(
            "target_dir must be a valid filesystem path.",
            error_type="validation_error",
            code="invalid_target_dir",
        )
    return Path(text).expanduser().resolve()


def _resolve_python_executable(python_executable: str | None) -> str:
    executable = python_executable or sys.executable
    if not isinstance(executable, str) or not executable.strip() or "\x00" in executable:
        raise MCPVideoError(
            "python_executable must be a valid executable path.",
            error_type="validation_error",
            code="invalid_python_executable",
        )
    return str(Path(executable).expanduser().resolve())


def _build_launcher_script(python_executable: str, *, is_windows: bool) -> str:
    if is_windows:
        safe_exe = python_executable.replace('"', '""')
        return f'@echo off\r\n"{safe_exe}" -m kinocut.native_messaging %*\r\n'
    quoted = shlex.quote(python_executable)
    return f'#!/usr/bin/env sh\nexec {quoted} -m kinocut.native_messaging "$@"\n'


def build_manifest_payload(extension_id: str, launcher_path: Path) -> dict[str, Any]:
    """Build the Chrome Native Messaging host manifest dictionary."""
    valid_id = validate_extension_id(extension_id)
    return {
        "name": NATIVE_HOST_NAME,
        "description": NATIVE_HOST_DESCRIPTION,
        "path": str(launcher_path.resolve()),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{valid_id}/"],
    }


def _atomic_write_text(path: Path, content: str, *, mode: int | None = None, newline: str = "\n") -> None:
    """Atomically write UTF-8 text to *path* with fsync and optional POSIX mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline=newline,
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None and os.name != "nt":
            os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)
        raise


def install_native_host(
    extension_id: str,
    *,
    browser: str = "chrome",
    target_dir: str | Path | None = None,
    python_executable: str | None = None,
    platform_name: str | None = None,
) -> dict[str, Any]:
    """Install the Native Messaging host manifest and executable launcher atomically."""
    valid_id = validate_extension_id(extension_id)
    normalized_browser = validate_browser(browser)
    plat = (platform_name or sys.platform).lower()
    is_windows = plat.startswith("win")
    manifest_dir = _resolve_manifest_dir(normalized_browser, target_dir, plat)
    executable = _resolve_python_executable(python_executable)

    launcher_name = "kinocut-native-host.bat" if is_windows else "kinocut-native-host.sh"
    launcher_path = manifest_dir / launcher_name
    manifest_path = manifest_dir / f"{NATIVE_HOST_NAME}.json"

    launcher_body = _build_launcher_script(executable, is_windows=is_windows)
    _atomic_write_text(
        launcher_path,
        launcher_body,
        mode=None if is_windows else 0o755,
        newline="" if is_windows else "\n",
    )

    payload = build_manifest_payload(valid_id, launcher_path)
    _atomic_write_text(manifest_path, json.dumps(payload, indent=2) + "\n", mode=None if is_windows else 0o644)

    return {
        "success": True,
        "action": "install",
        "host_name": NATIVE_HOST_NAME,
        "browser": normalized_browser,
        "manifest_path": str(manifest_path),
        "launcher_path": str(launcher_path),
        "allowed_origins": payload["allowed_origins"],
    }


def uninstall_native_host(
    *,
    browser: str = "chrome",
    target_dir: str | Path | None = None,
    platform_name: str | None = None,
) -> dict[str, Any]:
    """Remove the installed Native Messaging host manifest and launcher script."""
    normalized_browser = validate_browser(browser)
    plat = (platform_name or sys.platform).lower()
    manifest_dir = _resolve_manifest_dir(normalized_browser, target_dir, plat)
    manifest_path = manifest_dir / f"{NATIVE_HOST_NAME}.json"

    removed_manifest = False
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest_path.unlink()
        removed_manifest = True

    removed_launchers: list[str] = []
    for name in ("kinocut-native-host.sh", "kinocut-native-host.bat"):
        candidate = manifest_dir / name
        if candidate.exists() or candidate.is_symlink():
            candidate.unlink()
            removed_launchers.append(str(candidate))

    return {
        "success": True,
        "action": "uninstall",
        "host_name": NATIVE_HOST_NAME,
        "browser": normalized_browser,
        "manifest_path": str(manifest_path),
        "removed": removed_manifest,
        "removed_launchers": removed_launchers,
    }
