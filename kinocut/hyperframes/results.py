"""Translate CLI output into typed Hyperframes results."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from ..defaults import DEFAULT_REMOVE_BACKGROUND_MODEL
from ..validation import REMOVE_BACKGROUND_HF_BACKEND
from .models import HyperframesJsonResult


def _parse_json_stdout(stdout: str) -> dict[str, Any] | list[Any] | str:
    """Parse Hyperframes JSON output, preserving text when a command is human-only."""
    text = stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _json_result(command: str, result: subprocess.CompletedProcess[str]) -> HyperframesJsonResult:
    return HyperframesJsonResult(command=command, data=_parse_json_stdout(result.stdout), stdout=result.stdout)


# Hyperframes doctor checks that only gate optional features (transcription,
# local TTS/music fallbacks, Docker renders, optional npm packages). A failure
# here must not mark the whole environment as broken.
HYPERFRAMES_DOCTOR_OPTIONAL_CHECKS = frozenset(
    {
        "whisper-cpp",
        "TTS (Kokoro)",
        "BGM (MusicGen)",
        "Docker",
        "Docker running",
        "onnxruntime-node",
        "@google/genai",
    }
)


def _doctor_check_is_optional(check: dict[str, Any]) -> bool:
    name = str(check.get("name", ""))
    detail = str(check.get("detail", ""))
    return name in HYPERFRAMES_DOCTOR_OPTIONAL_CHECKS or "(optional" in detail.lower()


def _doctor_result(result: subprocess.CompletedProcess[str]) -> HyperframesJsonResult:
    """Build the doctor result with a verdict that tracks required checks.

    ``success`` is False when any required check fails, so exit codes and
    MCP callers agree with the doctor's own report.
    """
    parsed = _json_result("doctor", result)
    data = parsed.data
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        return parsed
    checks = [c for c in data["checks"] if isinstance(c, dict)]
    failed_required = [str(c.get("name", "")) for c in checks if not c.get("ok") and not _doctor_check_is_optional(c)]
    failed_optional = [str(c.get("name", "")) for c in checks if not c.get("ok") and _doctor_check_is_optional(c)]
    data = {
        **data,
        "required_ok": not failed_required,
        "failed_required": failed_required,
        "failed_optional": failed_optional,
    }
    return parsed.model_copy(update={"success": not failed_required, "data": data})


def _hf_remove_background_result(result: subprocess.CompletedProcess[str]) -> HyperframesJsonResult:
    payload = _parse_json_stdout(result.stdout)
    if isinstance(payload, dict):
        payload.setdefault("model", DEFAULT_REMOVE_BACKGROUND_MODEL)
        payload.setdefault("backend", REMOVE_BACKGROUND_HF_BACKEND)
        stdout = json.dumps(payload, sort_keys=True)
    else:
        stdout = result.stdout
    return HyperframesJsonResult(command="remove-background", data=payload, stdout=stdout)
