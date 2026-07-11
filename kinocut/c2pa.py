"""C2PA provenance signing provider for final path-based exports."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .defaults import DEFAULT_C2PA_TIMEOUT
from .errors import C2PASigningError, C2PAToolNotFoundError, C2PAVerificationError, MCPVideoError
from .ffmpeg_helpers import _validate_artifact_path, _validate_input_path, _validate_output_path


_UNTRUSTED_SIGNING_CREDENTIAL_STATUS = "signingCredential.untrusted"
_UNTRUSTED_SIGNING_CREDENTIAL_WARNING = "signing_credential_untrusted"


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
        "trusted": verification["trusted"],
        "warning_codes": verification["warning_codes"],
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
        if verification:
            raise C2PAVerificationError("c2patool verification command failed")
        stderr = result.stderr[-500:] if result.stderr else ""
        stdout = result.stdout[-500:] if result.stdout else ""
        detail = stderr or stdout or f"c2patool exited with {result.returncode}"
        raise C2PASigningError(detail)
    return result


def _verify_signed_asset(tool: str, asset: str) -> dict[str, Any]:
    result = _run_c2patool([tool, asset], "verify", verification=True)
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError as exc:
        raise C2PAVerificationError(f"c2patool returned non-JSON verification output: {exc}") from exc
    if not isinstance(payload, dict):
        raise C2PAVerificationError("c2patool verification output was not a JSON object")

    active_manifest = payload.get("active_manifest")
    manifests = payload.get("manifests")
    has_active_manifest = isinstance(active_manifest, str) and bool(active_manifest.strip())
    manifest_count = _manifest_count(manifests)
    if not has_active_manifest and manifest_count == 0:
        raise C2PAVerificationError("c2patool verification output did not include a manifest")
    if payload.get("validation_state") != "Valid":
        raise C2PAVerificationError("c2patool verification state was not Valid")

    validation_status = payload.get("validation_status", [])
    if not isinstance(validation_status, list):
        raise C2PAVerificationError("c2patool verification status was not a list")
    trusted = True
    warning_codes: list[str] = []
    if validation_status:
        if _is_untrusted_signing_credential_only(validation_status):
            trusted = False
            warning_codes.append(_UNTRUSTED_SIGNING_CREDENTIAL_WARNING)
        else:
            raise C2PAVerificationError("c2patool verification reported fatal validation status")
    return {
        "active_manifest": has_active_manifest,
        "manifest_count": manifest_count,
        "trusted": trusted,
        "warning_codes": warning_codes,
    }


def _is_untrusted_signing_credential_only(validation_status: Any) -> bool:
    if not isinstance(validation_status, list) or len(validation_status) != 1:
        return False
    status = validation_status[0]
    return isinstance(status, dict) and status.get("code") == _UNTRUSTED_SIGNING_CREDENTIAL_STATUS


def _manifest_count(manifests: Any) -> int:
    if isinstance(manifests, dict):
        return sum(
            1
            for label, manifest in manifests.items()
            if isinstance(label, str) and bool(label.strip()) and isinstance(manifest, dict)
        )
    return 0
