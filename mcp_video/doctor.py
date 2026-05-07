"""Environment diagnostics for mcp-video integrations."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from .limits import DOCTOR_COMMAND_TIMEOUT

WhichFn = Callable[[str], str | None]
VersionRunner = Callable[[list[str]], str | None]
FindSpecFn = Callable[[str], Any]
PackageVersionFn = Callable[[str], str | None]

PYTHON_313_UPSCALE_BACKEND_HINT = (
    "Real-ESRGAN/BasicSR are skipped on Python 3.13+ because BasicSR currently fails to build there. "
    'The OpenCV fallback is still installed by: pip install "mcp-video[upscale]". '
    "Use Python 3.11 or 3.12 if you specifically need the Real-ESRGAN backend."
)

COMMAND_CHECKS = (
    {
        "name": "ffmpeg",
        "category": "core",
        "required": True,
        "command": ["ffmpeg", "-version"],
        "install_hint": "Install FFmpeg: brew install ffmpeg, apt install ffmpeg, or download from https://ffmpeg.org/download.html",
    },
    {
        "name": "ffprobe",
        "category": "core",
        "required": True,
        "command": ["ffprobe", "-version"],
        "install_hint": "Install FFmpeg, which includes ffprobe.",
    },
    {
        "name": "node",
        "category": "hyperframes",
        "required": False,
        "command": ["node", "--version"],
        "install_hint": "Install Node.js 22+ for Hyperframes features.",
    },
    {
        "name": "npx",
        "category": "hyperframes",
        "required": False,
        "command": ["npx", "--version"],
        "install_hint": "Install npx/npm for Hyperframes CLI execution.",
    },
)

PACKAGE_CHECKS = (
    ("mcp", "mcp", "core", True, "Install the base package: pip install mcp-video"),
    ("pydantic", "pydantic", "core", True, "Install the base package: pip install mcp-video"),
    ("rich", "rich", "core", True, "Install the base package: pip install mcp-video"),
    ("pillow", "PIL", "image", False, 'Install image extras: pip install "mcp-video[image]"'),
    ("scikit-learn", "sklearn", "image", False, 'Install image extras: pip install "mcp-video[image]"'),
    ("webcolors", "webcolors", "image", False, 'Install image extras: pip install "mcp-video[image]"'),
    ("anthropic", "anthropic", "image-ai", False, 'Install image AI extras: pip install "mcp-video[image-ai]"'),
    ("openai-whisper", "whisper", "ai", False, 'Install transcription extras: pip install "mcp-video[transcribe]"'),
    ("demucs", "demucs", "ai", False, 'Install stem-separation extras: pip install "mcp-video[stems]"'),
    ("realesrgan", "realesrgan", "ai", False, 'Install upscale extras: pip install "mcp-video[upscale]"'),
    ("basicsr", "basicsr", "ai", False, 'Install upscale extras: pip install "mcp-video[upscale]"'),
    ("numpy", "numpy", "ai", False, 'Install upscale extras: pip install "mcp-video[upscale]"'),
    ("opencv-contrib-python", "cv2", "ai", False, 'Install upscale extras: pip install "mcp-video[upscale]"'),
    (
        "torch",
        "torch",
        "ai",
        False,
        'Install stem/upscale extras: pip install "mcp-video[stems]" or "mcp-video[upscale]"',
    ),
    ("torchaudio", "torchaudio", "ai", False, 'Install stem-separation extras: pip install "mcp-video[stems]"'),
    ("torchcodec", "torchcodec", "ai", False, 'Install stem-separation extras: pip install "mcp-video[stems]"'),
    ("imagehash", "imagehash", "ai", False, 'Install AI scene extras: pip install "mcp-video[ai-scene]"'),
)


def _command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=DOCTOR_COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    first_line = (result.stdout or result.stderr).splitlines()[0:1]
    return first_line[0].strip() if first_line else None


def _package_version(distribution_name: str) -> str | None:
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _check_command(definition: dict[str, Any], which: WhichFn, version_runner: VersionRunner) -> dict[str, Any]:
    path = which(definition["name"])
    version = version_runner(definition["command"]) if path else None
    ok = path is not None and version is not None
    return {
        "name": definition["name"],
        "category": definition["category"],
        "required": definition["required"],
        "ok": ok,
        "path": path,
        "version": version,
        "install_hint": None if ok else definition["install_hint"],
    }


def _check_package(
    distribution_name: str,
    import_name: str,
    category: str,
    required: bool,
    install_hint: str,
    find_spec: FindSpecFn,
    package_version: PackageVersionFn,
) -> dict[str, Any]:
    found = find_spec(import_name) is not None
    version = package_version(distribution_name) if found else None
    ok = found and version is not None
    if not ok and distribution_name in {"realesrgan", "basicsr"} and sys.version_info >= (3, 13):
        install_hint = PYTHON_313_UPSCALE_BACKEND_HINT
    return {
        "name": distribution_name,
        "category": category,
        "required": required,
        "ok": ok,
        "path": None,
        "version": version if ok else None,
        "install_hint": None if ok else install_hint,
    }


def _summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    required = [check for check in checks if check["required"]]
    optional = [check for check in checks if not check["required"]]
    missing_required = [check["name"] for check in required if not check["ok"]]
    missing_optional = [check["name"] for check in optional if not check["ok"]]
    return {
        "required_ok": not missing_required,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "total_checks": len(checks),
        "passed": sum(1 for check in checks if check["ok"]),
        "optional_available": sum(1 for check in optional if check["ok"]),
    }


def run_diagnostics(
    *,
    which: WhichFn = shutil.which,
    version_runner: VersionRunner = _command_version,
    find_spec: FindSpecFn = importlib.util.find_spec,
    package_version: PackageVersionFn = _package_version,
) -> dict[str, Any]:
    """Return a structured report for core and optional integration dependencies."""
    checks = [_check_command(definition, which, version_runner) for definition in COMMAND_CHECKS]
    checks.extend(
        _check_package(*definition, find_spec=find_spec, package_version=package_version)
        for definition in PACKAGE_CHECKS
    )
    return {
        "success": True,
        "platform": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "system": platform.platform(),
        },
        "summary": _summary(checks),
        "checks": checks,
    }
