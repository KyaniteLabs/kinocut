"""Environment diagnostics for Kinocut integrations."""

from __future__ import annotations

import logging
import os
import platform
import re
import sys
from collections.abc import Callable
from typing import Any

from concurrent.futures import ThreadPoolExecutor

from ._install_hints import pip_install_hint, pinned_requirement
from dataclasses import replace
from .host_probes import HostProbes, without_machine_paths
from .rescue.capabilities import captions_available, snapshot_capabilities
from .doctor_offline import (
    check_offline_readiness,
    check_hyperframes_cli as _check_hyperframes_cli,
    check_sphere_director,
    report_resolved_hyperframes,
)
from .type_names import exception_kind
from .defaults import (
    DEFAULT_HYPERFRAMES_TELEMETRY,
    DEFAULT_OVERWRITE,
    DEFAULT_REVIDEO_TELEMETRY,
    DEFAULT_VISION_MODE,
    MIN_FFMPEG_VERSION,
    MIN_FFMPEG_VERSION_HARD,
    MIN_PYTHON_VERSION,
)

logger = logging.getLogger(__name__)
_DEFAULT_PROBES = HostProbes()


WhichFn = Callable[[str], str | None]
VersionRunner = Callable[[list[str]], str | None]
FindSpecFn = Callable[[str], Any]
PackageVersionFn = Callable[[str], str | None]
ImportModuleFn = Callable[[str], Any]

LEGACY_UPSCALE_BACKEND_HINT = (
    "Real-ESRGAN/BasicSR require a separately validated, compatible environment. "
    "BasicSR 1.4.2 imports a module removed by modern TorchVision. "
    f"Use the OpenCV fallback installed by: {pip_install_hint('upscale')}."
)
_UPSCALE_IMPORTS = {
    "realesrgan": "from realesrgan import RealESRGANer",
    "basicsr": "from basicsr.archs.rrdbnet_arch import RRDBNet",
    "opencv-contrib-python": "import cv2; assert callable(cv2.dnn_superres.DnnSuperResImpl_create)",
}

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
    ("mcp", "mcp", "core", True, f"Install the base package: {pip_install_hint(quoted=False)}"),
    ("pydantic", "pydantic", "core", True, f"Install the base package: {pip_install_hint(quoted=False)}"),
    ("rich", "rich", "core", True, f"Install the base package: {pip_install_hint(quoted=False)}"),
    ("pillow", "PIL", "image", False, f"Install image extras: {pip_install_hint('image')}"),
    ("scikit-learn", "sklearn", "image", False, f"Install image extras: {pip_install_hint('image')}"),
    ("webcolors", "webcolors", "image", False, f"Install image extras: {pip_install_hint('image')}"),
    ("anthropic", "anthropic", "image-ai", False, f"Install image AI extras: {pip_install_hint('image-ai')}"),
    (
        "openai-whisper",
        "whisper",
        "ai",
        False,
        f"Install transcription extras: {pip_install_hint('transcribe')}",
    ),
    ("demucs", "demucs", "ai", False, f"Install stem-separation extras: {pip_install_hint('stems')}"),
    ("realesrgan", "realesrgan", "ai", False, LEGACY_UPSCALE_BACKEND_HINT),
    ("basicsr", "basicsr", "ai", False, LEGACY_UPSCALE_BACKEND_HINT),
    ("numpy", "numpy", "audio", False, f"Install audio extras: {pip_install_hint('audio')}"),
    ("opencv-contrib-python", "cv2", "ai", False, f"Install upscale extras: {pip_install_hint('upscale')}"),
    ("torch", "torch", "ai", False, f"Install stem-separation extras: {pip_install_hint('stems')}"),
    ("torchaudio", "torchaudio", "ai", False, f"Install stem-separation extras: {pip_install_hint('stems')}"),
    ("torchcodec", "torchcodec", "ai", False, f"Install stem-separation extras: {pip_install_hint('stems')}"),
    ("imagehash", "imagehash", "ai", False, f"Install AI scene extras: {pip_install_hint('ai-scene')}"),
    (
        "scipy",
        "scipy",
        "audio-enhanced",
        False,
        f"Install enhanced audio extras: {pip_install_hint('audio-enhanced')}",
    ),
    (
        "soundfile",
        "soundfile",
        "audio-enhanced",
        False,
        f"Install enhanced audio extras: {pip_install_hint('audio-enhanced')}",
    ),
)


def _parse_ffmpeg_version(version_line: str | None, tool_name: str = "ffmpeg") -> int | None:
    """Extract major version number from '<tool> version [n]X.Y...' string."""
    if not version_line:
        return None
    m = re.search(rf"\b{re.escape(tool_name)}\s+version\s+(?:n(?=\d))?(\d+)(?:\.\d+)*\b", version_line, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _is_recognized_ffmpeg_snapshot(version_line: str | None, tool_name: str) -> bool:
    """Return True for legitimate non-release FFmpeg/ffprobe git snapshot banners."""
    if not version_line:
        return False
    return bool(
        re.search(
            rf"\b{re.escape(tool_name)}\s+version\s+(?:N-\d+|git-[0-9a-f]+|\d{{4}}-\d{{2}}-\d{{2}}-git)\b",
            version_line,
            re.IGNORECASE,
        )
    )


def _parse_python_version(version_line: str | None) -> tuple[int, int] | None:
    """Extract major and minor versions from a Python version line."""
    if not version_line:
        return None
    match = re.search(r"\bPython\s+(\d+)\.(\d+)", version_line, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def _check_command(definition: dict[str, Any], probes: HostProbes) -> dict[str, Any]:
    if definition.get("probe") == "never":
        # The doctor does not run a package manager. It reports whether one is
        # on PATH and leaves it there.
        path = probes.which(definition["command"][0])
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
    path = probes.which(definition["command"][0])
    raw_version = probes.command_version(definition["command"], path) if path else None
    version = raw_version.strip() if isinstance(raw_version, str) and raw_version.strip() else None
    ok = path is not None and version is not None
    extra: dict[str, Any] = {}

    if path is not None and version is None and definition["required"]:
        extra["reason"] = "empty_version_output"

    # FFmpeg / ffprobe version enforcement — fail closed on unrecognized banners.
    if definition["name"] in {"ffmpeg", "ffprobe"} and ok:
        tool_name = definition["name"]
        major = _parse_ffmpeg_version(version, tool_name=tool_name)
        if major is not None:
            extra["major_version"] = major
            if major < MIN_FFMPEG_VERSION_HARD:
                ok = False
                extra["reason"] = "unsupported_version"
                extra["install_hint"] = (
                    f"{tool_name} {major}.x is too old. Kinocut requires FFmpeg {MIN_FFMPEG_VERSION}+. "
                    "Update: brew upgrade ffmpeg, apt upgrade ffmpeg, or download from https://ffmpeg.org"
                )
            elif major < MIN_FFMPEG_VERSION:
                extra["warning"] = (
                    f"{tool_name} {major}.x works but {MIN_FFMPEG_VERSION}+ is recommended for full feature support."
                )
        elif not _is_recognized_ffmpeg_snapshot(version, tool_name):
            ok = False
            extra["reason"] = "unrecognized_version"
            extra["install_hint"] = (
                f"Could not verify {tool_name} version from banner output. {definition['install_hint']}"
            )

    if definition["name"] == "python" and ok:
        python_version = _parse_python_version(version)
        if python_version is None:
            ok = False
            extra["reason"] = "unrecognized_version"
        elif python_version < MIN_PYTHON_VERSION:
            ok = False
            extra["reason"] = "unsupported_version"

    if definition["name"] == "node" and ok and (hyperframes_path := probes.which("hyperframes")):
        extra.update(report_resolved_hyperframes(hyperframes_path, probes=probes))

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
    probes: HostProbes,
) -> dict[str, Any]:
    found = probes.find_spec(import_name) is not None
    version = probes.package_version(distribution_name) if found else None
    ok = found and version is not None
    probe = _UPSCALE_IMPORTS.get(distribution_name)
    real_package_probes = (
        probes.find_spec is _DEFAULT_PROBES.find_spec and probes.package_version is _DEFAULT_PROBES.package_version
    )
    if ok and probe and (real_package_probes or probes.version_runner is not _DEFAULT_PROBES.version_runner):
        marker = probes.version_runner([sys.executable, "-P", "-c", f"{probe}; print('import ok')"])
        ok = marker is not None
        if not ok:
            install_hint = f"Installed, but the backend import failed or timed out. {install_hint}"
    return {
        "name": distribution_name,
        "category": category,
        "required": required,
        "ok": ok,
        "path": None,
        "version": version if ok else None,
        "install_hint": None if ok else install_hint,
    }


def _check_crush(probes: HostProbes) -> dict[str, Any]:
    path = probes.crush_sources()
    return {
        "name": "crush_shaders",
        "category": "crush",
        "required": False,
        "ok": path is not None,
        "path": str(path) if path else None,
        "version": None,
        "install_hint": None
        if path
        else "Set MCP_VIDEO_CRUSH_PATH to the local crush-js/src directory containing common.glsl, or place it under KINOCUT_DATA_DIR/crush-js/src.",
    }


def _check_audio_engine(probes: HostProbes) -> dict[str, Any]:
    """Check audio engine capabilities."""
    has_numpy = probes.find_spec("numpy") is not None
    has_scipy = probes.find_spec("scipy") is not None
    has_pedalboard = probes.find_spec("pedalboard") is not None

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
        "install_hint": None if has_numpy else f"{pip_install_hint('audio')} for professional audio synthesis",
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
        "install_hint": None if found else f"Install the local package: {pip_install_hint(quoted=False)}",
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


def _check_hyperframes_core(probes: HostProbes) -> dict[str, Any]:
    command = ["node", "-e", HYPERFRAMES_CORE_PROBE]
    path = probes.which("node")
    version = probes.command_version(command, path) if path else None
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


def _check_alias_identity(probes: HostProbes = _DEFAULT_PROBES) -> dict[str, Any]:
    """Verify the kinocut <-> mcp_video rename preserved one shared Client (#56).

    A read-only migration signal: after the 1.7 identity cutover, importing
    ``kinocut`` and ``mcp_video`` must yield the same ``Client`` object. A
    divergent alias means a stale or partial install that will surface as a
    confusing "two clients" failure downstream.
    """

    try:
        kinocut = probes.import_module("kinocut")
        mcp_video = probes.import_module("mcp_video")
    except Exception:  # pragma: no cover - defensive: a broken install is the signal
        return {
            "name": "alias_identity",
            "category": "migration",
            "ok": False,
            "detail": "unable to import kinocut/mcp_video",
            "remediation": f"Reinstall the package: pip install --force-reinstall {pinned_requirement()}",
        }
    ok = hasattr(kinocut, "Client") and kinocut.Client is getattr(mcp_video, "Client", None)
    return {
        "name": "alias_identity",
        "category": "migration",
        "ok": ok,
        "detail": "kinocut.Client is mcp_video.Client" if ok else "Client objects diverged after rename",
        "remediation": (
            "The 1.7 rename must keep one Client. Reinstall kinocut so that mcp_video.Client is kinocut.Client."
        ),
    }


def _check_legacy_env_paths(probes: HostProbes = _DEFAULT_PROBES) -> dict[str, Any]:
    """Flag stale pre-rename env vars and paths awaiting migration (#56)."""

    stale_env = probes.environ.get("MCP_VIDEO_CRUSH_PATH")
    legacy_dir = probes.home() / ".mcp-video"
    findings: list[str] = []
    if stale_env:
        # The value is the operator's own environment: the report says the
        # variable is set, not what it says.
        findings.append("MCP_VIDEO_CRUSH_PATH is set")
    if legacy_dir.exists():
        # The name of the directory is ours; the path it sits in is not.
        findings.append("the legacy directory ~/.mcp-video exists")
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
            "~/.mcp-video (kinocut now uses KINOCUT_* / ~/.kinocut; KINOCUT_DATA_DIR sets where models, fonts and CRUSH live)."
        ),
    }


def _check_workspace(probes: HostProbes = _DEFAULT_PROBES) -> dict[str, Any]:
    """Report read/write access and free space without writing a probe file."""

    workspace, readable, writable, free_bytes = probes.workspace()
    return {
        "name": "workspace",
        "category": "core",
        "required": False,
        "ok": readable and writable and free_bytes is not None,
        "path": str(workspace),
        "version": None,
        "permissions": {"read": readable, "write": writable},
        "disk_free_bytes": free_bytes,
        "install_hint": None if readable and writable else "Choose a readable and writable local workspace.",
    }


def _policy_setting(probes: HostProbes, name: str, default: Any) -> dict[str, Any]:
    """A setting's name, its shipped default, and whether it is overridden.

    The value the operator chose is their configuration: the report says
    which setting is theirs and what the default is, not what they set.
    """
    return {
        "setting": name,
        "default": default,
        "state": "default" if name not in probes.environ else "custom",
    }


def _check_runtime_policy(probes: HostProbes) -> dict[str, Any]:
    """Expose effective guardrail defaults without changing any policy."""

    flags = {
        "overwrite_default": DEFAULT_OVERWRITE,
        "network_egress_default": False,
        "vision_mode": _policy_setting(probes, "KINOCUT_VISION_MODE", DEFAULT_VISION_MODE),
        "hyperframes_telemetry": _policy_setting(
            probes, "KINOCUT_HYPERFRAMES_TELEMETRY", str(DEFAULT_HYPERFRAMES_TELEMETRY)
        ),
        "revideo_telemetry": _policy_setting(probes, "KINOCUT_REVIDEO_TELEMETRY", str(DEFAULT_REVIDEO_TELEMETRY)),
        "mcp_tools": probes.tool_mode(),
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


def _rescue_summary(checks: list[dict[str, Any]], probes: HostProbes) -> dict[str, Any]:
    by_name = {check["name"]: check for check in checks}
    core_ready = all(by_name.get(name, {}).get("ok") for name in ("ffmpeg", "ffprobe"))
    capabilities = snapshot_capabilities(probes=probes)
    captions = core_ready and captions_available(capabilities)
    automatic = [
        "audio_loudness",
        "container_timestamps",
        "exposure",
        "metadata",
        "rotation",
        "universal_mp4",
    ]
    if not core_ready or not capabilities["ffmpeg"]["available"]:
        automatic.clear()
    else:
        if not capabilities["filters"]["loudnorm"]:
            automatic.remove("audio_loudness")
        if not capabilities["filters"]["eq"]:
            automatic.remove("exposure")
        if not capabilities["filters"]["transpose"]:
            automatic.remove("rotation")
    if captions:
        automatic.append("captions")
    return {
        "core_ready": core_ready,
        "local_only": True,
        "captions_available": captions,
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
            # The exception's own text can carry a path; the report names
            # the kind, and the log above keeps the detail for the operator.
            "detail": exception_kind(exc),
            "install_hint": (
                "Run 'kino --mcp' to see the full error; usually a broken install "
                f"(pip install --force-reinstall {pinned_requirement()}) or a platform-specific dependency issue."
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
    probes: HostProbes | None = None,
    which: WhichFn | None = None,
    version_runner: VersionRunner | None = None,
    find_spec: FindSpecFn | None = None,
    package_version: PackageVersionFn | None = None,
    import_module: ImportModuleFn | None = None,
    include_paths: bool = True,
) -> dict[str, Any]:
    """Return a structured report for core and optional integration dependencies.

    The report names the machine's own paths, which is what an operator
    running this locally needs. A caller that hands the report onward — the
    MCP tool — asks for the paths to be left out.
    """
    probes = probes or HostProbes()
    probes = replace(
        probes,
        which=which or probes.which,
        version_runner=version_runner or probes.version_runner,
        legacy_command_runner=version_runner or probes.legacy_command_runner,
        find_spec=find_spec or probes.find_spec,
        package_version=package_version or probes.package_version,
        import_module=import_module or probes.import_module,
    )
    checks = [
        _check_mcp_video(probes.find_spec, probes.package_version),
        _check_mcp_server_import(probes.import_module),
    ]
    with ThreadPoolExecutor(max_workers=min(8, len(COMMAND_CHECKS))) as pool:
        checks.extend(pool.map(lambda definition: _check_command(definition, probes), COMMAND_CHECKS))
    checks.extend(
        [
            _check_hyperframes_cli(probes),
            _check_hyperframes_core(probes),
        ]
    )
    checks.extend(_check_package(*definition, probes=probes) for definition in PACKAGE_CHECKS)
    checks.append(_check_crush(probes))
    checks.append(_check_audio_engine(probes))
    checks.append(_check_still_plates(probes.find_spec, probes.package_version))
    checks.append(_check_object_matte(probes))
    checks.append(check_sphere_director(probes))
    checks.append(check_offline_readiness(probes, include_paths=include_paths))
    checks.extend([_check_workspace(probes), _check_runtime_policy(probes)])
    report = {
        "success": True,
        "platform": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "system": platform.platform(),
        },
        "summary": _summary(checks),
        "checks": checks,
        "rescue": _rescue_summary(checks, probes),
        "migrations": [_check_alias_identity(probes), _check_legacy_env_paths(probes)],
    }
    return report if include_paths else without_machine_paths(report)


def _object_matte_runtime(probes: HostProbes) -> tuple[bool, list[str]]:
    try:
        ort = probes.import_module("onnxruntime")

        return True, list(ort.get_available_providers())
    except Exception as exc:
        logger.warning("onnxruntime provider probe failed: %s", exc)
        return False, []


def _check_object_matte(probes: HostProbes) -> dict[str, Any]:
    """Report product/object matte readiness. Never downloads weights."""
    from .validation import OBJECT_MATTE_WEIGHTS_SHA256

    spec_ok = probes.find_spec("onnxruntime") is not None
    runtime_ok, providers = _object_matte_runtime(probes) if spec_ok else (False, [])
    cache_path, cached, digest = probes.matte_weights()
    hash_match = digest == OBJECT_MATTE_WEIGHTS_SHA256
    ok = runtime_ok and cached and hash_match
    hint = None
    if not ok:
        hint = (
            f"Product/object cutouts need {pip_install_hint('object-matte')} "
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
            f"Install: {pip_install_hint('image')}. "
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
