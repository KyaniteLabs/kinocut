"""C2PA provenance signing provider for final path-based exports."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

from .defaults import DEFAULT_C2PA_TIMEOUT
from .errors import C2PASigningError, C2PAToolNotFoundError, C2PAVerificationError, MCPVideoError
from .ffmpeg_helpers import _validate_artifact_path, _validate_input_path, _validate_output_path


def sign_export_with_c2pa(
    asset_path: str,
    *,
    manifest_path: str,
    tool_path: str | None = None,
    signer_path: str | None = None,
) -> dict[str, Any]:
    """Add and verify a C2PA manifest on an already-rendered final export."""
    asset = _validate_input_path(asset_path)
    manifest = _validate_manifest_path(manifest_path)
    tool = _resolve_c2patool(tool_path)

    suffix = Path(asset).suffix
    signed_tmp = str(Path(asset).with_name(f"{Path(asset).stem}.c2pa-signing{suffix}"))
    _validate_output_path(signed_tmp)
    if os.path.exists(signed_tmp):
        os.remove(signed_tmp)

    cmd = [tool, asset, "--manifest", manifest, "--output", signed_tmp, "--force"]
    if signer_path:
        cmd.extend(["--signer-path", signer_path])

    _run_c2patool(cmd, "sign")
    if not os.path.isfile(signed_tmp):
        raise C2PASigningError("c2patool completed without producing the signed output")

    try:
        verification = _verify_signed_asset(tool, signed_tmp)
    except Exception:
        if os.path.exists(signed_tmp):
            os.remove(signed_tmp)
        raise

    os.replace(signed_tmp, asset)
    return {
        "status": "signed",
        "verified": True,
        "manifest_sha256": _sha256_file(manifest),
        "verification": verification,
    }


def _validate_manifest_path(path: str) -> str:
    if not path.lower().endswith(".json"):
        raise MCPVideoError(
            "c2pa_manifest_path must point to a .json manifest definition file",
            error_type="validation_error",
            code="invalid_c2pa_manifest",
        )
    _validate_artifact_path(path)
    if not os.path.isfile(path):
        raise MCPVideoError(
            f"C2PA manifest file not found: {path}",
            error_type="input_error",
            code="invalid_c2pa_manifest",
        )
    return os.path.realpath(path)


def _resolve_c2patool(tool_path: str | None) -> str:
    candidate = tool_path or os.environ.get("KINOCUT_C2PATOOL") or os.environ.get("MCP_VIDEO_C2PATOOL") or "c2patool"
    resolved = shutil.which(candidate) if os.path.basename(candidate) == candidate else candidate
    if resolved is None or not os.path.isfile(resolved) or not os.access(resolved, os.X_OK):
        raise C2PAToolNotFoundError(candidate)
    return os.path.realpath(resolved)


def _run_c2patool(
    cmd: list[str],
    phase: str,
    *,
    verification: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DEFAULT_C2PA_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        if verification:
            raise C2PAVerificationError(f"{phase} timed out after {DEFAULT_C2PA_TIMEOUT}s") from exc
        raise C2PASigningError(f"{phase} timed out after {DEFAULT_C2PA_TIMEOUT}s", code="c2pa_timeout") from exc
    if result.returncode != 0:
        stderr = result.stderr[-500:] if result.stderr else ""
        stdout = result.stdout[-500:] if result.stdout else ""
        detail = stderr or stdout or f"c2patool exited with {result.returncode}"
        if verification:
            raise C2PAVerificationError(detail)
        raise C2PASigningError(detail)
    return result


def _verify_signed_asset(tool: str, asset: str) -> dict[str, Any]:
    result = _run_c2patool([tool, asset], "verify", verification=True)
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError as exc:
        raise C2PAVerificationError(f"c2patool returned non-JSON verification output: {exc}") from exc

    validation_status = payload.get("validation_status")
    if validation_status:
        raise C2PAVerificationError(json.dumps(validation_status, sort_keys=True))
    active_manifest = payload.get("active_manifest")
    manifests = payload.get("manifests")
    manifest_count = _manifest_count(manifests)
    if not active_manifest and manifest_count == 0:
        raise C2PAVerificationError("c2patool verification output did not include a manifest")
    return {
        "active_manifest": bool(active_manifest),
        "manifest_count": manifest_count,
        "validation_status": [],
    }


def _manifest_count(manifests: Any) -> int:
    if isinstance(manifests, dict):
        return len(manifests)
    if isinstance(manifests, list):
        return len(manifests)
    return 0


def _sha256_file(path: str) -> str:
    digest = sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
