"""Operator-owned permission for Kinocut's optional provider calls."""

import os
import re

from .defaults import DEFAULT_VISION_MODE
from .errors import MCPVideoError
from .validation import VISION_MODES


def vision_provider_allowed(endpoint_kind: str | None = None, *, fixed_origin: bool = False) -> bool:
    """Credentials never grant permission; a fixed cloud worker cannot serve local/custom routes."""
    mode = os.environ.get("KINOCUT_VISION_MODE", DEFAULT_VISION_MODE).strip().lower()
    if mode not in VISION_MODES:
        raise MCPVideoError("KINOCUT_VISION_MODE must be off, local or remote", error_type="validation_error")
    if mode == "off":
        return False
    if fixed_origin:
        return mode == "remote" and not os.environ.get("KINOCUT_VISION_BASE_URL", "").strip()
    return mode == "remote" or endpoint_kind == "local"


def require_vision_provider(endpoint_kind: str | None = None, *, fixed_origin: bool = False) -> None:
    """Guard execution even when a caller bypasses a public tool handler."""
    if not vision_provider_allowed(endpoint_kind, fixed_origin=fixed_origin):
        raise MCPVideoError(
            "Vision provider execution is disabled for this route. Use host image inspection, "
            "or explicitly configure KINOCUT_VISION_MODE (off/local/remote). "
            "The legacy QC worker cannot use a local or custom endpoint.",
            error_type="validation_error",
            code="vision_provider_disabled",
        )


_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)


def strip_think_blocks(text: str) -> str:
    """Drop reasoning-model <think> blocks, including an unterminated trailing one."""
    cleaned = _THINK_RE.sub("", text)
    cleaned = re.sub(r"<think(?:ing)?>.*\Z", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()
