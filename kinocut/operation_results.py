"""Transport-independent result envelopes for media operations."""

import logging
from typing import Any

from .errors import MCPVideoError, retry_message

logger = logging.getLogger(__name__)


def _error_result(err: MCPVideoError | Exception) -> dict[str, Any]:
    if isinstance(err, MCPVideoError):
        return {"success": False, "error": err.to_dict()}
    # Unexpected exception — log full traceback, return generic message
    logger.exception("Unexpected error in media operation")
    return {
        "success": False,
        "error": {
            "type": "internal_error",
            "code": "internal_error",
            "message": retry_message(
                "An internal error occurred. Check server logs for details.",
                "internal_error",
            ),
        },
    }


def _result(result: Any) -> dict[str, Any]:
    if result is None:
        return {
            "success": False,
            "error": {"type": "processing_error", "code": "no_result", "message": "Operation returned no result"},
        }
    if hasattr(result, "model_dump"):
        data = result.model_dump()
        # Include thumbnail_base64 only if it was generated (keep MCP responses lean)
        if not data.get("thumbnail_base64"):
            data.pop("thumbnail_base64", None)
        return data
    if isinstance(result, dict):
        result.setdefault("success", True)
        return result
    return {"success": True, "output_path": str(result)}
