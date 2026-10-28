"""Environment diagnostics for Kinocut integrations."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from concurrent.futures import ThreadPoolExecutor

from .doctor_offline import offline_probe_environment, report_resolved_hyperframes
from .defaults import (
    DEFAULT_HYPERFRAMES_TELEMETRY,
    DEFAULT_OVERWRITE,
    DEFAULT_REVIDEO_TELEMETRY,
    DEFAULT_VISION_MODE,
    MIN_FFMPEG_VERSION,
    MIN_FFMPEG_VERSION_HARD,
    MIN_PYTHON_VERSION,
)
from .limits import DOCTOR_COMMAND_TIMEOUT

logger = logging.getLogger(__name__)


WhichFn = Callable[[str], str | None]
VersionRunner = Callable[[list[str]], str | None]
FindSpecFn = Callable[[str], Any]
PackageVersionFn = Callable[[str], str | None]
ImportModuleFn = Callable[[str], Any]

PYTHON_313_UPSCALE_BACKEND_HINT = (
    "Real-ESRGAN/BasicSR are skipped on Python 3.13+ because BasicSR currently fails to build there. "
    'The OpenCV fallback is still installed by: pip install "kinocut[upscale]==1.16.5". '
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
        # A package manager is never executed: `npx --version` can consult
        # the registry. Its presence is read from PATH instead.
        "probe": "never",
        "install_hint": "Install npx/npm only if your chosen Hyperframes package layout uses it.",
    },
    {
        "name": "npm",
        "category": "hyperframes",
        "required": False,
        "command": ["npm", "--version"],
        "probe": "never",
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
    ("mcp", "mcp", "core", True, "Install the base package: pip install kinocut==1.16.5"),
    ("pydantic", "pydantic", "core", True, "Install the base package: pip install kinocut==1.16.5"),
    ("rich", "rich", "core", True, "Install the base package: pip install kinocut==1.16.5"),
    ("pillow", "PIL", "image", False, 'Install image extras: pip install "kinocut[image]==1.16.5"'),
    ("scikit-learn", "sklearn", "image", False, 'Install image extras: pip install "kinocut[image]==1.16.5"'),
    ("webcolors", "webcolors", "image", False, 'Install image extras: pip install "kinocut[image]==1.16.5"'),
    ("anthropic", "anthropic", "image-ai", False, 'Install image AI extras: pip install "kinocut[image-ai]==1.16.5"'),
    (
        "openai-whisper",
        "whisper",
        "ai",
        False,
        'Install transcription extras: pip install "kinocut[transcribe]==1.16.5"',
    ),
    ("demucs", "demucs", "ai", False, 'Install stem-separation extras: pip install "kinocut[stems]==1.16.5"'),
    ("realesrgan", "realesrgan", "ai", False, 'Install upscale extras: pip install "kinocut[upscale]==1.16.5"'),
    ("basicsr", "basicsr", "ai", False, 'Install upscale extras: pip install "kinocut[upscale]==1.16.5"'),
    ("numpy", "numpy", "audio", False, 'Install audio extras: pip install "kinocut[audio]==1.16.5"'),
    ("opencv-contrib-python", "cv2", "ai", False, 'Install upscale extras: pip install "kinocut[upscale]==1.16.5"'),
    (
        "torch",
        "torch",
        "ai",
        False,
        'Install stem/upscale extras: pip install "kinocut[stems]==1.16.5" or "kinocut[upscale]==1.16.5"',
    ),
    ("torchaudio", "torchaudio", "ai", False, 'Install stem-separation extras: pip install "kinocut[stems]==1.16.5"'),
    ("torchcodec", "torchcodec", "ai", False, 'Install stem-separation extras: pip install "kinocut[stems]==1.16.5"'),
    ("imagehash", "imagehash", "ai", False, 'Install AI scene extras: pip install "kinocut[ai-scene]==1.16.5"'),
    (
        "scipy",
        "scipy",
        "audio-enhanced",
        False,
        'Install enhanced audio extras: pip install "kinocut[audio-enhanced]==1.16.5"',
    ),
    (
        "soundfile",
        "soundfile",
        "audio-enhanced",
        False,
        'Install enhanced audio extras: pip install "kinocut[audio-enhanced]==1.16.5"',
    ),
    (
        "librosa",
        "librosa",
        "audio-enhanced",
        False,
        'Install enhanced audio extras: pip install "kinocut[audio-enhanced]==1.16.5"',
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


def _parse_python_version(version_line: str | None) -> tuple[int, int] | None:
    """Extract major and minor versions from a Python version line."""
    if not version_line:
        return None
    match = re.search(r"\bPython\s+(\d+)\.(\d+)", version_line, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _doctor_probe_environment() -> dict[str, str]:
    """The environment a version probe runs in: sanitized and update-disabled.

    A PATH-only shim can carry its own installer or updater, and the caller's
    environment can carry provider credentials. A version probe needs neither,
    so both are removed.
    """
    return offline_probe_environment()


def _command_version(command: list[str]) -> str | None:
    """Run a version probe offline.

    The probe inherits the caller's environment, which can carry provider
    credentials and can point a shim at an updater that reaches the network.
    Doctor's own comment says it must stay offline, so the probe runs with the
    same sanitized, update-disabled environment the Hyperframes engine uses.
    """
    try:
        result = subprocess.run(  # noqa: S603
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=DOCTOR_COMMAND_TIMEOUT,
            env=_doctor_probe_environment(),
        )
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
    if definition.get("probe") == "never":
        # The doctor does not run a package manager. It reports whether one is
        # on PATH and leaves it there.
        path = which(definition["command"][0])
        return {
            "name": definition["name"],
            "category": definition["category"],
            "required": definition["required"],
            "ok": path is not None,
            "path": path,
            "version": None,
            "command": definition["command"],
            "install_hint": None,
            "probed": False,
            "reason": "the doctor does not run a package manager; its presence is read from PATH, not executed",
        }
    path = which(definition["command"][0])
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

    if definition["name"] == "python" and ok:
        python_version = _parse_python_version(version)
        if python_version is not None and python_version < MIN_PYTHON_VERSION:
            ok = False

    # Hyperframes version check — routed through the injectable version_runner
    # so tests can exercise both outcomes (a raw subprocess call here would be
    # untestable, the same defect class as the @hyperframes/core probe).
    hyperframes_path = which("hyperframes")
    if definition["name"] == "node" and ok and hyperframes_path:
        # Invoke the already-resolved executable directly. `npx --yes` may
        # consult the npm registry when PATH resolution and npm's local bins
        # disagree (a shim outside npm's bin dirs); doctor must stay offline.
        extra.update(report_resolved_hyperframes(hyperframes_path))

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
        "install_hint": None if has_numpy else 'pip install "kinocut[audio]==1.16.5" for professional audio synthesis',
        "details": {
            "numpy": has_numpy,
            "scipy": has_scipy,
            "pedalboard": has_pedalboard,
        },
    }


def _check_mcp_video(find_spec: FindSpecFn, package_version: PackageVersionFn) -> dict[str, Any]:
    spec = find_spec("kinocut")
    path = getattr(spec, "origin", None) if spec is not None else None
    if path is not None:
        # Report platform-stable separators so diagnostics compare and grep
        # identically across Windows and POSIX (#447).
        path = path.replace(os.sep, "/")
    found = spec is not None
    return {
        "name": "mcp-video",
        "category": "core",
        "required": True,
        "ok": found,
        "path": path,
        "version": package_version("kinocut") if found else None,
        "install_hint": None if found else "Install the local package: pip install kinocut==1.16.5",
    }


def _check_hyperframes_cli(which: WhichFn) -> dict[str, Any]:
    from .doctor_offline import check_hyperframes_cli

    return check_hyperframes_cli(which)


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


def _check_alias_identity() -> dict[str, Any]:
    """Verify the kinocut <-> mcp_video rename preserved one shared Client (#56).

    A read-only migration signal: after the 1.7 identity cutover, importing
    ``kinocut`` and ``mcp_video`` must yield the same ``Client`` object. A
    divergent alias means a stale or partial install that will surface as a
    confusing "two clients" failure downstream.
    """

    try:
        import kinocut
        import mcp_video
    except Exception:  # pragma: no cover - defensive: a broken install is the signal
        return {
            "name": "alias_identity",
            "category": "migration",
            "ok": False,
            "detail": "unable to import kinocut/mcp_video",
            "remediation": "Reinstall the package: pip install --force-reinstall kinocut==1.16.5",
        }
    ok = getattr(kinocut, "Client", None) is getattr(mcp_video, "Client", None)
    return {
        "name": "alias_identity",
        "category": "migration",
        "ok": ok,
        "detail": "kinocut.Client is mcp_video.Client" if ok else "Client objects diverged after rename",
        "remediation": (
            "The 1.7 rename must keep one Client. Reinstall kinocut so that mcp_video.Client is kinocut.Client."
        ),
    }


def _check_legacy_env_paths() -> dict[str, Any]:
    """Flag stale pre-rename env vars and paths awaiting migration (#56)."""

    stale_env = os.environ.get("MCP_VIDEO_CRUSH_PATH")
    legacy_dir = Path.home() / ".mcp-video"
    findings: list[str] = []
    if stale_env:
        findings.append(f"env MCP_VIDEO_CRUSH_PATH={stale_env}")
    if legacy_dir.exists():
        findings.append(f"legacy path {legacy_dir}")
    ok = not findings
    return {
        "name": "legacy_env_paths",
        "category": "migration",
        "ok": ok,
        "detail": "; ".join(findings) if findings else "clean",
        "remediation": (
            "No stale pre-rename paths."
            if ok
            else "Remove stale pre-1.7 state: unset MCP_VIDEO_CRUSH_PATH and delete "
            "~/.mcp-video (kinocut now uses KINOCUT_* / ~/.kinocut)."
        ),
    }


def _check_workspace() -> dict[str, Any]:
    """Report read/write access and free space without writing a probe file."""

    workspace = Path.cwd()
    try:
        usage = shutil.disk_usage(workspace)
        readable = os.access(workspace, os.R_OK)
        writable = os.access(workspace, os.W_OK)
        free_bytes = usage.free
    except OSError:
        readable = writable = False
        free_bytes = None
    return {
        "name": "workspace",
        "category": "core",
        "required": True,
        "ok": readable and writable and free_bytes is not None,
        "path": str(workspace),
        "version": None,
        "permissions": {"read": readable, "write": writable},
        "disk_free_bytes": free_bytes,
        "install_hint": None if readable and writable else "Choose a readable and writable local workspace.",
    }


def _check_runtime_policy() -> dict[str, Any]:
    """Expose effective guardrail defaults without changing any policy."""

    from .tool_registry import active_mode

    flags = {
        "overwrite_default": DEFAULT_OVERWRITE,
        "network_egress_default": False,
        "vision_mode": os.environ.get("KINOCUT_VISION_MODE", DEFAULT_VISION_MODE),
        "hyperframes_telemetry": os.environ.get("KINOCUT_HYPERFRAMES_TELEMETRY", str(DEFAULT_HYPERFRAMES_TELEMETRY)),
        "revideo_telemetry": os.environ.get("KINOCUT_REVIDEO_TELEMETRY", str(DEFAULT_REVIDEO_TELEMETRY)),
        "mcp_tools": active_mode(),
    }
    return {
        "name": "runtime_policy",
        "category": "core",
        "required": False,
        "ok": True,
        "path": None,
        "version": None,
        "flags": flags,
        "install_hint": None,
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


def _check_mcp_server_import(import_module: ImportModuleFn) -> dict[str, Any]:
    """Import the MCP server tool tree so 'doctor OK' covers ``kino --mcp`` (#445).

    The package checks prove ``mcp`` exists on disk, not that the server tree
    imports. A platform-specific import failure (a POSIX-only module, a broken
    optional dependency) left ``kino --mcp`` dead while doctor reported OK —
    so this check exercises the same import the entry point performs.
    """

    try:
        import_module("kinocut.server")
    except Exception as exc:  # the failure is the signal; doctor must never crash on it
        logger.warning("MCP server import check failed for kinocut.server: %s", exc)
        return {
            "name": "mcp-server-import",
            "category": "core",
            "required": True,
            "ok": False,
            "detail": f"{type(exc).__name__}: {exc}",
            "install_hint": (
                "Run 'kino --mcp' to see the full error; usually a broken install "
                "(pip install --force-reinstall kinocut==1.16.5) or a platform-specific dependency issue."
            ),
        }
    return {
        "name": "mcp-server-import",
        "category": "core",
        "required": True,
        "ok": True,
        "detail": "kinocut.server imports cleanly",
    }


def run_diagnostics(
    *,
    which: WhichFn = shutil.which,
    version_runner: VersionRunner = _command_version,
    find_spec: FindSpecFn = importlib.util.find_spec,
    package_version: PackageVersionFn = _package_version,
    import_module: ImportModuleFn = importlib.import_module,
) -> dict[str, Any]:
    """Return a structured report for core and optional integration dependencies."""
    checks = [_check_mcp_video(find_spec, package_version), _check_mcp_server_import(import_module)]
    with ThreadPoolExecutor(max_workers=min(8, len(COMMAND_CHECKS))) as pool:
        checks.extend(pool.map(lambda definition: _check_command(definition, which, version_runner), COMMAND_CHECKS))
    checks.extend(
        [
            _check_hyperframes_cli(which),
            _check_hyperframes_core(which, version_runner),
        ]
    )
    checks.extend(
        _check_package(*definition, find_spec=find_spec, package_version=package_version)
        for definition in PACKAGE_CHECKS
    )
    checks.append(_check_crush())
    checks.append(_check_audio_engine())
    checks.append(_check_still_plates(find_spec, package_version))
    checks.append(_check_object_matte(find_spec))
    checks.append(_check_sphere_director())
    checks.extend([_check_workspace(), _check_runtime_policy()])
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
        "migrations": [_check_alias_identity(), _check_legacy_env_paths()],
    }


def _check_sphere_director() -> dict[str, Any]:
    """Report configured 360 director backends (probe only, no network)."""
    from kinocut.te.sphere_director import detect_sphere_director

    detected = detect_sphere_director()
    return {
        "name": "sphere_director",
        "category": "optional",
        "required": False,
        "ok": True,
        "path": None,
        "version": detected.get("id"),
        "install_hint": None,
        "details": detected,
    }


def _object_matte_cache_path() -> Path:
    from .validation import object_matte_cache_path

    return object_matte_cache_path()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object_matte_runtime() -> tuple[bool, list[str]]:
    try:
        import onnxruntime as ort

        return True, list(ort.get_available_providers())
    except Exception as exc:
        logger.warning("onnxruntime provider probe failed: %s", exc)
        return False, []


def _check_object_matte(find_spec: FindSpecFn) -> dict[str, Any]:
    """Report product/object matte readiness. Never downloads weights."""
    from .validation import OBJECT_MATTE_WEIGHTS_BYTES, OBJECT_MATTE_WEIGHTS_SHA256

    spec_ok = find_spec("onnxruntime") is not None
    runtime_ok, providers = _object_matte_runtime() if spec_ok else (False, [])
    cache_path = _object_matte_cache_path()
    cached = cache_path.is_file()
    digest = None
    hash_match = False
    if cached and cache_path.stat().st_size == OBJECT_MATTE_WEIGHTS_BYTES:
        digest = _sha256_file(cache_path)
        hash_match = digest == OBJECT_MATTE_WEIGHTS_SHA256
    ok = runtime_ok and cached and hash_match
    hint = None
    if not ok:
        hint = (
            'Product/object cutouts need pip install "kinocut[object-matte]==1.16.5" '
            "and the pinned BiRefNet-general weights. "
            "People cutouts: omit --model. Guide: docs/PRODUCT_MATTE.md."
        )
    return {
        "name": "object_matte",
        "category": "object-matte",
        "required": False,
        "ok": ok,
        "path": str(cache_path) if cached else None,
        "version": None,
        "install_hint": hint,
        "details": {
            "onnxruntime": runtime_ok,
            "weightsCached": cached,
            "sha256": digest,
            "sha256Match": hash_match,
            "expectedSha256": OBJECT_MATTE_WEIGHTS_SHA256,
            "providers": providers,
            "docs": "docs/PRODUCT_MATTE.md",
        },
    }


def _check_still_plates(find_spec: FindSpecFn, package_version: PackageVersionFn) -> dict[str, Any]:
    """Report still/plate editor capability (image stack + free edit backend)."""
    pillow_ok = find_spec("PIL") is not None
    numpy_ok = find_spec("numpy") is not None
    ok = pillow_ok and numpy_ok
    version = package_version("pillow") if pillow_ok else None
    missing = []
    if not pillow_ok:
        missing.append("pillow")
    if not numpy_ok:
        missing.append("numpy")
    hint = None
    if not ok:
        hint = (
            "Still/plate tools need the image stack (Pillow + NumPy). "
            'Install: pip install "kinocut[image]==1.16.5". '
            "Free establish-locked edit uses local match; no paid still-generation adapter exists."
        )
    return {
        "name": "still_plates",
        "category": "still-plates",
        "required": False,
        "ok": ok,
        "path": None,
        "version": version,
        "install_hint": hint,
        "details": {
            "pillow": pillow_ok,
            "numpy": numpy_ok,
            "free_edit_backend": "free_establish_match" if ok else "unavailable",
            "paid_gen_backend": "adapter_unavailable",
            "missing": missing,
            "docs": "docs/STILL_PLATES.md",
        },
    }
