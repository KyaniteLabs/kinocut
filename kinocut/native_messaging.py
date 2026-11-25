"""Local Chrome Native Messaging host for Kinocut.

Implements the standard Chrome Native Messaging binary stdio protocol
(4-byte unsigned little-endian length prefix + UTF-8 JSON body, <= 1 MiB)
over a strict allowlist of read-only inspection and confirmation-gated actions.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from typing import Any, BinaryIO

import kinocut
from .direct import executor as direct_executor
from .doctor import run_diagnostics
from .engine_probe import probe
from .errors import MCPVideoError, ValidationError
from .ffmpeg_helpers import _validate_input_path
from .native_messaging_install import (
    NATIVE_HOST_NAME,
    SUPPORTED_BROWSERS,
    install_native_host,
    uninstall_native_host,
)
from .offline import is_offline_mode
from .output_policy import output_operation
from .quality_guardrails import quality_check
from .request_log import redact_text
from .review_card import write_review_card
from .validation_errors import exception_kind

PROTOCOL_VERSION = "kinocut-native-v1"
MAX_MESSAGE_BYTES = 1_048_576  # 1 MiB hard cap per Chrome Native Messaging spec
ALLOWED_ACTIONS = frozenset(
    {
        "ping",
        "doctor",
        "info",
        "quality_check",
        "direct_plan",
        "direct_apply",
        "review_card",
    }
)
ALLOWED_QUALITY_PROFILES = frozenset({"default", "dark-grade", "ui-capture-dark", "ui-capture-light"})


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    """Read up to *size* bytes from *stream*, looping across short reads."""
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one length-prefixed JSON frame from *stream*. Returns None on clean EOF."""
    header = _read_exact(stream, 4)
    if not header:
        return None
    if len(header) < 4:
        raise MCPVideoError(
            "Truncated Native Messaging frame header.",
            error_type="protocol_error",
            code="truncated_frame",
        )
    (length,) = struct.unpack("<I", header)
    if length == 0:
        raise MCPVideoError(
            "Native Messaging frame length must be positive.",
            error_type="protocol_error",
            code="empty_frame",
        )
    if length > MAX_MESSAGE_BYTES:
        raise MCPVideoError(
            f"Native Messaging frame exceeds maximum size of {MAX_MESSAGE_BYTES} bytes.",
            error_type="protocol_error",
            code="frame_too_large",
        )
    body = _read_exact(stream, length)
    if len(body) < length:
        raise MCPVideoError(
            "Truncated Native Messaging frame body.",
            error_type="protocol_error",
            code="truncated_frame",
        )
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MCPVideoError(
            "Native Messaging frame is not valid UTF-8.",
            error_type="protocol_error",
            code="invalid_utf8",
        ) from exc
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise MCPVideoError(
            "Native Messaging frame is not valid JSON.",
            error_type="protocol_error",
            code="invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise MCPVideoError(
            "Native Messaging payload must be a JSON object.",
            error_type="protocol_error",
            code="invalid_payload",
        )
    return payload


def write_frame(stream: BinaryIO, payload: dict[str, Any]) -> None:
    """Serialize *payload* as a 4-byte length-prefixed UTF-8 JSON frame."""
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise MCPVideoError(
            f"Outbound Native Messaging frame exceeds maximum size of {MAX_MESSAGE_BYTES} bytes.",
            error_type="protocol_error",
            code="frame_too_large",
        )
    stream.write(struct.pack("<I", len(encoded)))
    stream.write(encoded)
    stream.flush()


def _safe_request_id(raw_id: Any) -> str | int | None:
    if type(raw_id) is int or isinstance(raw_id, str):
        return raw_id[:128] if isinstance(raw_id, str) else raw_id
    return None


def _error_response(exc: BaseException, request_id: str | int | None = None) -> dict[str, Any]:
    """Convert any exception into a redacted, value-free error envelope."""
    if isinstance(exc, MCPVideoError):
        error_dict = exc.to_dict()
        error_dict["message"] = redact_text(str(error_dict.get("message", "")))
    else:
        error_dict = {
            "type": "internal_error",
            "code": "unexpected_error",
            "message": f"Native Messaging action failed ({exception_kind(exc)}).",
        }
    response: dict[str, Any] = {"success": False, "error": error_dict}
    if request_id is not None:
        response["id"] = request_id
    return response


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(key, "is required and must be a non-empty string")
    return value


def _optional_str(params: dict[str, Any], key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(key, "must be a non-empty string")
    return value


def _require_bool(params: dict[str, Any], key: str, *, default: bool = False) -> bool:
    if key not in params or params[key] is None:
        return default
    value = params[key]
    if type(value) is not bool:
        raise ValidationError(key, "must be an explicit boolean")
    return value


def _handle_ping(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "version": kinocut.__version__,
        "offline": is_offline_mode(),
        "protocol": PROTOCOL_VERSION,
    }


def _find_check(checks: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for item in checks:
        if item.get("name") == name:
            return item
    return None


def _handle_doctor(_params: dict[str, Any]) -> dict[str, Any]:
    report = run_diagnostics(include_paths=False)
    summary = report.get("summary", {})
    checks = report.get("checks", [])
    ffmpeg_check = _find_check(checks, "ffmpeg")
    ffprobe_check = _find_check(checks, "ffprobe")
    offline_check = _find_check(checks, "offline_readiness")
    offline_details = (offline_check or {}).get("details", {})
    return {
        "success": True,
        "required_ok": bool(summary.get("required_ok", False)),
        "summary": summary,
        "offline": is_offline_mode(),
        "offline_readiness": {
            "ok": bool(offline_check.get("ok", False)) if offline_check else False,
            "enabled": bool(offline_details.get("enabled", False)),
            "features": offline_details.get("features", {}),
        },
        "ffmpeg": {
            "ok": bool(ffmpeg_check.get("ok", False)) if ffmpeg_check else False,
            "version": ffmpeg_check.get("version") if ffmpeg_check else None,
            "major_version": ffmpeg_check.get("major_version") if ffmpeg_check else None,
        },
        "ffprobe": {
            "ok": bool(ffprobe_check.get("ok", False)) if ffprobe_check else False,
            "version": ffprobe_check.get("version") if ffprobe_check else None,
            "major_version": ffprobe_check.get("major_version") if ffprobe_check else None,
        },
    }


def _handle_info(params: dict[str, Any]) -> dict[str, Any]:
    validated = _validate_input_path(_require_str(params, "input_path"))
    info = probe(validated)
    return {"success": True, "info": info.model_dump()}


def _handle_quality_check(params: dict[str, Any]) -> dict[str, Any]:
    validated = _validate_input_path(_require_str(params, "input_path"))
    profile = _optional_str(params, "profile") or "default"
    if profile not in ALLOWED_QUALITY_PROFILES:
        raise ValidationError(
            "profile",
            "must be one of default, dark-grade, ui-capture-dark, or ui-capture-light",
        )
    fail_on_warning = _require_bool(params, "fail_on_warning", default=False)
    report = quality_check(validated, fail_on_warning=fail_on_warning, profile=profile)
    return {
        "success": True,
        "profile": profile,
        "all_passed": report.get("all_passed"),
        "overall_score": report.get("overall_score"),
        "report": report,
    }


def _handle_direct_plan(params: dict[str, Any]) -> dict[str, Any]:
    validated = _validate_input_path(_require_str(params, "input_path"))
    direction = _require_str(params, "direction")
    output_path = _optional_str(params, "output_path")
    return direct_executor.review(validated, direction=direction, output_path=output_path)


def _handle_direct_apply(params: dict[str, Any]) -> dict[str, Any]:
    if params.get("confirm") is not True:
        raise MCPVideoError(
            "Direct apply requires explicit confirm=true before rendering.",
            error_type="confirmation_error",
            code="confirmation_required",
        )
    overwrite = _require_bool(params, "overwrite", default=False)
    plan = params.get("plan")
    if not isinstance(plan, dict):
        raise ValidationError("plan", "is required and must be a JSON object")
    direct_executor._ensure_no_unresolved_questions(plan)
    with output_operation(overwrite):
        return direct_executor.apply(plan, confirm=True)


def _handle_review_card(params: dict[str, Any]) -> dict[str, Any]:
    validated = _validate_input_path(_require_str(params, "input_path"))
    output_path = _optional_str(params, "output_path")
    overwrite = _require_bool(params, "overwrite", default=False)
    frame_count = params.get("frame_count", 6)
    if type(frame_count) is not int:
        raise ValidationError("frame_count", "must be an integer between 1 and 100")
    with output_operation(overwrite):
        return write_review_card(validated, output_path=output_path, frame_count=frame_count)


_ACTION_HANDLERS = {
    "ping": _handle_ping,
    "doctor": _handle_doctor,
    "info": _handle_info,
    "quality_check": _handle_quality_check,
    "direct_plan": _handle_direct_plan,
    "direct_apply": _handle_direct_apply,
    "review_card": _handle_review_card,
}


def _extract_params(message: dict[str, Any]) -> dict[str, Any]:
    if "params" in message and message["params"] is not None:
        raw_params = message["params"]
        if not isinstance(raw_params, dict):
            raise ValidationError("params", "must be a JSON object")
        return raw_params
    return {k: v for k, v in message.items() if k not in {"action", "id", "params"}}


def dispatch_message(message: dict[str, Any]) -> dict[str, Any]:
    """Validate and execute one allowlisted Native Messaging request."""
    request_id = _safe_request_id(message.get("id"))
    try:
        action = message.get("action")
        if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
            raise MCPVideoError(
                "Unsupported Native Messaging action.",
                error_type="validation_error",
                code="unsupported_action",
            )
        params = _extract_params(message)
        result = _ACTION_HANDLERS[action](params)
        if not isinstance(result, dict):
            result = {"success": True, "result": result}
        if request_id is not None:
            result = {**result, "id": request_id}
        return result
    except Exception as exc:
        return _error_response(exc, request_id=request_id)


def serve_stdio(stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> int:
    """Run the Chrome Native Messaging binary stdio message loop until EOF."""
    in_stream = stdin if stdin is not None else sys.stdin.buffer
    out_stream = stdout if stdout is not None else sys.stdout.buffer
    while True:
        try:
            message = read_frame(in_stream)
        except MCPVideoError as exc:
            write_frame(out_stream, _error_response(exc))
            return 1
        if message is None:
            return 0
        response = dispatch_message(message)
        try:
            write_frame(out_stream, response)
        except MCPVideoError as exc:
            request_id = _safe_request_id(message.get("id"))
            write_frame(out_stream, _error_response(exc, request_id=request_id))
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kinocut.native_messaging",
        description=f"Kinocut Chrome Native Messaging host ({NATIVE_HOST_NAME}).",
    )
    parser.add_argument("--install", action="store_true", help="Install the Native Messaging host manifest.")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall the Native Messaging host manifest.")
    parser.add_argument("--extension-id", help="32-character Chrome extension ID (lowercase a-p).")
    parser.add_argument(
        "--browser",
        default="chrome",
        choices=SUPPORTED_BROWSERS,
        help="Target Chromium-family browser (default: chrome).",
    )
    parser.add_argument("--target-dir", help="Override target manifest directory.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: serve stdio by default, or install/uninstall the host manifest."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.install and args.uninstall:
        error = MCPVideoError(
            "Cannot combine --install and --uninstall in the same invocation.",
            error_type="validation_error",
            code="conflicting_flags",
        )
        print(json.dumps(_error_response(error)), file=sys.stderr)
        return 2
    if args.install:
        try:
            result = install_native_host(
                args.extension_id,
                browser=args.browser,
                target_dir=args.target_dir,
            )
        except MCPVideoError as exc:
            print(json.dumps(_error_response(exc)), file=sys.stderr)
            return 2
        print(json.dumps(result))
        return 0
    if args.uninstall:
        try:
            result = uninstall_native_host(browser=args.browser, target_dir=args.target_dir)
        except MCPVideoError as exc:
            print(json.dumps(_error_response(exc)), file=sys.stderr)
            return 2
        print(json.dumps(result))
        return 0
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
