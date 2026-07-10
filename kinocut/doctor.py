"""Environment diagnostics for mcp-video integrations."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import HyperframesNotFoundError
from .hyperframes_engine import HYPERFRAMES_COMMAND_ENV, _hyperframes_command_prefix
from .defaults import MIN_FFMPEG_VERSION, MIN_FFMPEG_VERSION_HARD
from .limits import DOCTOR_COMMAND_TIMEOUT

WhichFn = Callable[[str], str | None]
VersionRunner = Callable[[list[str]], str | None]
FindSpecFn = Callable[[str], Any]
PackageVersionFn = Callable[[str], str | None]

PYTHON_313_UPSCALE_BACKEND_HINT = (
    "Real-ESRGAN/BasicSR are skipped on Python 3.13+ because BasicSR currently fails to build there. "
    'The OpenCV fallback is still installed by: pip install "kinocut[upscale]". '
    "Use Python 3.11 or 3.12 if you specifically need the Real-ESRGAN backend."
)

BASIC_PITCH_MANUAL_HINT = (
    "BasicPitch is a manual optional integration because its TensorFlow dependency chain is not safely "
    "resolvable by the package extras. Use Python 3.11 or 3.12 if you specifically need audio AI pitch extraction."
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
        "install_hint": "Install npx/npm only if your chosen Hyperframes package layout uses it.",
    },
    {
        "name": "npm",
        "category": "hyperframes",
        "required": False,
        "command": ["npm", "--version"],
        "install_hint": "Install npm for Hyperframes package diagnostics.",
    },
    {
        "name": "python",
        "category": "core",
        "required": False,
        "command": ["python3", "--version"],
        "install_hint": "Python 3.11+ is required.",
    },
)

PACKAGE_CHECKS = (
    ("mcp", "mcp", "core", True, "Install the base package: pip install kinocut"),
    ("pydantic", "pydantic", "core", True, "Install the base package: pip install kinocut"),
    ("rich", "rich", "core", True, "Install the base package: pip install kinocut"),
    ("pillow", "PIL", "image", False, 'Install image extras: pip install "kinocut[image]"'),
    ("scikit-learn", "sklearn", "image", False, 'Install image extras: pip install "kinocut[image]"'),
    ("webcolors", "webcolors", "image", False, 'Install image extras: pip install "kinocut[image]"'),
    ("anthropic", "anthropic", "image-ai", False, 'Install image AI extras: pip install "kinocut[image-ai]"'),
    ("openai-whisper", "whisper", "ai", False, 'Install transcription extras: pip install "kinocut[transcribe]"'),
    ("demucs", "demucs", "ai", False, 'Install stem-separation extras: pip install "kinocut[stems]"'),
    ("realesrgan", "realesrgan", "ai", False, 'Install upscale extras: pip install "kinocut[upscale]"'),
    ("basicsr", "basicsr", "ai", False, 'Install upscale extras: pip install "kinocut[upscale]"'),
    ("numpy", "numpy", "audio", False, 'Install audio extras: pip install "kinocut[audio]"'),
    ("opencv-contrib-python", "cv2", "ai", False, 'Install upscale extras: pip install "kinocut[upscale]"'),
    (
        "torch",
        "torch",
        "ai",
        False,
        'Install stem/upscale extras: pip install "kinocut[stems]" or "kinocut[upscale]"',
    ),
    ("torchaudio", "torchaudio", "ai", False, 'Install stem-separation extras: pip install "kinocut[stems]"'),
    ("torchcodec", "torchcodec", "ai", False, 'Install stem-separation extras: pip install "kinocut[stems]"'),
    ("imagehash", "imagehash", "ai", False, 'Install AI scene extras: pip install "kinocut[ai-scene]"'),
    (
        "scipy",
        "scipy",
        "audio-enhanced",
        False,
        'Install enhanced audio extras: pip install "kinocut[audio-enhanced]"',
    ),
    (
        "soundfile",
        "soundfile",
        "audio-enhanced",
        False,
        'Install enhanced audio extras: pip install "kinocut[audio-enhanced]"',
    ),
    (
        "librosa",
        "librosa",
        "audio-enhanced",
        False,
        'Install enhanced audio extras: pip install "kinocut[audio-enhanced]"',
    ),
    ("basic-pitch", "basic_pitch", "audio-ai", False, BASIC_PITCH_MANUAL_HINT),
    (
        "meltysynth",
        "meltysynth",
        "manual-midi",
        False,
        "MeltySynth is not currently published on PyPI; install a compatible meltysynth module manually.",
    ),
)


def _parse_ffmpeg_version(version_line: str | None) -> int | None:
    """Extract major version number from 'ffmpeg version X.Y...' string."""
    if not version_line:
        return None
    m = re.search(r"ffmpeg version (\d+)", version_line, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=DOCTOR_COMMAND_TIMEOUT)  # noqa: S603
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
    extra: dict[str, Any] = {}

    # FFmpeg version enforcement
    if definition["name"] == "ffmpeg" and ok:
        major = _parse_ffmpeg_version(version)
        if major is not None:
            extra["major_version"] = major
            if major < MIN_FFMPEG_VERSION_HARD:
                ok = False
                extra["install_hint"] = (
                    f"FFmpeg {major}.x is too old. Kinocut requires FFmpeg {MIN_FFMPEG_VERSION}+. "
                    "Update: brew upgrade ffmpeg, apt upgrade ffmpeg, or download from https://ffmpeg.org"
                )
            elif major < MIN_FFMPEG_VERSION:
                extra["warning"] = (
                    f"FFmpeg {major}.x works but {MIN_FFMPEG_VERSION}+ is recommended for full feature support."
                )

    # Hyperframes version check — routed through the injectable version_runner
    # so tests can exercise both outcomes (a raw subprocess call here would be
    # untestable, the same defect class as the @hyperframes/core probe).
    if definition["name"] == "node" and ok:
        hf_version = version_runner(["npx", "--yes", "hyperframes", "--version"])
        if hf_version:
            extra["hyperframes_version"] = hf_version

    return {
        "name": definition["name"],
        "category": definition["category"],
        "required": definition["required"],
        "ok": ok,
        "path": path,
        "version": version,
        "command": definition["command"],
        "install_hint": extra.get("install_hint", definition["install_hint"]) if not ok else None,
        **extra,
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
    elif not ok and distribution_name == "basic-pitch" and sys.version_info >= (3, 13):
        install_hint = BASIC_PITCH_MANUAL_HINT
    return {
        "name": distribution_name,
        "category": category,
        "required": required,
        "ok": ok,
        "path": None,
        "version": version if ok else None,
        "install_hint": None if ok else install_hint,
    }


def _check_crush() -> dict[str, Any]:
    """Check CRUSH shader availability."""
    env_path = os.environ.get("MCP_VIDEO_CRUSH_PATH")
    if env_path:
        p = Path(env_path).expanduser().resolve()
        if p.is_dir():
            return {
                "name": "crush_shaders",
                "category": "crush",
                "required": False,
                "ok": True,
                "path": str(p),
                "version": None,
                "install_hint": None,
            }

    home_path = Path.home() / ".mcp-video" / "crush-js" / "src"
    if home_path.is_dir():
        return {
            "name": "crush_shaders",
            "category": "crush",
            "required": False,
            "ok": True,
            "path": str(home_path),
            "version": None,
            "install_hint": None,
        }

    return {
        "name": "crush_shaders",
        "category": "crush",
        "required": False,
        "ok": False,
        "path": None,
        "version": None,
        "install_hint": (
            "CRUSH shaders not found. Set MCP_VIDEO_CRUSH_PATH env var or install to ~/.mcp-video/crush-js/src. "
            "See https://github.com/pushingsquares/crush for installation."
        ),
    }


def _check_audio_engine() -> dict[str, Any]:
    """Check audio engine capabilities."""
    has_numpy = importlib.util.find_spec("numpy") is not None
    has_scipy = importlib.util.find_spec("scipy") is not None
    has_pedalboard = importlib.util.find_spec("pedalboard") is not None

    status = "legacy"
    if has_numpy and has_scipy:
        status = "enhanced"
    elif has_numpy:
        status = "standard"

    return {
        "name": "audio_engine",
        "category": "audio",
        "required": False,
        "ok": has_numpy,
        "path": None,
        "version": status,
        "install_hint": None if has_numpy else 'pip install "kinocut[audio]" for professional audio synthesis',
        "details": {
            "numpy": has_numpy,
            "scipy": has_scipy,
            "pedalboard": has_pedalboard,
        },
    }


def _check_mcp_video(find_spec: FindSpecFn, package_version: PackageVersionFn) -> dict[str, Any]:
    spec = find_spec("kinocut")
    path = getattr(spec, "origin", None) if spec is not None else None
    found = spec is not None
    return {
        "name": "mcp-video",
        "category": "core",
        "required": True,
        "ok": found,
        "path": path,
        "version": package_version("kinocut") if found else None,
        "install_hint": None if found else "Install the local package: pip install kinocut",
    }


def _check_hyperframes_cli(which: WhichFn, version_runner: VersionRunner) -> dict[str, Any]:
    try:
        prefix = _hyperframes_command_prefix(which=which)
    except HyperframesNotFoundError:
        prefix = ["hyperframes"]
    command = [*prefix, "--version"]
    path = prefix[0] if prefix != ["hyperframes"] else which("hyperframes")
    version = version_runner(command) if path else None
    ok = path is not None and version is not None
    return {
        "name": "hyperframes",
        "category": "hyperframes",
        "required": False,
        "ok": ok,
        "path": path,
        "version": version,
        "command": command,
        "install_hint": None
        if ok
        else (f"Install a pinned Hyperframes package, add hyperframes to PATH, or set {HYPERFRAMES_COMMAND_ENV}."),
    }


# Probe for @hyperframes/core in the active Node package layout. The package is
# ESM-only with a restrictive "exports" map (no "./package.json" subpath and no
# "require" condition), so require()/require.resolve() throw
# ERR_PACKAGE_PATH_NOT_EXPORTED. Walk the node_modules resolution chain and read
# its package.json from disk instead.
HYPERFRAMES_CORE_PROBE = (
    "const fs=require('fs');const path=require('path');"
    "const dirs=require.resolve.paths('@hyperframes/core')||[];"
    "for(const dir of dirs){"
    "const file=path.join(dir,'@hyperframes/core','package.json');"
    "if(fs.existsSync(file)){"
    "console.log(JSON.parse(fs.readFileSync(file,'utf8')).version);process.exit(0);}}"
    "process.exit(1);"
)


def _check_hyperframes_core(which: WhichFn, version_runner: VersionRunner) -> dict[str, Any]:
    command = ["node", "-e", HYPERFRAMES_CORE_PROBE]
    path = which("node")
    version = version_runner(command) if path else None
    ok = path is not None and version is not None
    return {
        "name": "@hyperframes/core",
        "category": "hyperframes",
        "required": False,
        "ok": ok,
        "path": path,
        "version": version,
        "command": command,
        "install_hint": None if ok else "Install @hyperframes/core in the active Node package layout.",
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


def _rescue_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {check["name"]: check for check in checks}
    captions_available = bool(by_name.get("openai-whisper", {}).get("ok"))
    automatic = [
        "audio_loudness",
        "container_timestamps",
        "exposure",
        "metadata",
        "rotation",
        "universal_mp4",
    ]
    if captions_available:
        automatic.append("captions")
    return {
        "core_ready": all(by_name.get(name, {}).get("ok") for name in ("ffmpeg", "ffprobe")),
        "local_only": True,
        "captions_available": captions_available,
        "automatic_repair_types": automatic,
    }


def run_diagnostics(
    *,
    which: WhichFn = shutil.which,
    version_runner: VersionRunner = _command_version,
    find_spec: FindSpecFn = importlib.util.find_spec,
    package_version: PackageVersionFn = _package_version,
) -> dict[str, Any]:
    """Return a structured report for core and optional integration dependencies."""
    checks = [_check_mcp_video(find_spec, package_version)]
    checks.extend(_check_command(definition, which, version_runner) for definition in COMMAND_CHECKS)
    checks.extend(
        [
            _check_hyperframes_cli(which, version_runner),
            _check_hyperframes_core(which, version_runner),
        ]
    )
    checks.extend(
        _check_package(*definition, find_spec=find_spec, package_version=package_version)
        for definition in PACKAGE_CHECKS
    )
    checks.append(_check_crush())
    checks.append(_check_audio_engine())
    return {
        "success": True,
        "platform": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "system": platform.platform(),
        },
        "summary": _summary(checks),
        "checks": checks,
        "rescue": _rescue_summary(checks),
    }
