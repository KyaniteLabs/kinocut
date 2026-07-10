"""Shared FastMCP app and result helpers."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from .errors import MCPVideoError

mcp = FastMCP(
    "mcp-video",
    instructions=(
        "mcp-video is a video editing MCP server. Use these tools to trim, merge, "
        "add text overlays, sync audio, resize, convert, and export video files. "
        "All file paths should be absolute. Output files are generated automatically "
        "if no output_path is provided."
    ),
)

logger = logging.getLogger(__name__)


def _validation_error(message: str, code: str = "invalid_parameter") -> dict[str, Any]:
    """Return a structured validation-error result for MCP tool handlers.

    Eliminates the repeated 5-line ``return _error_result(MCPVideoError(...))``
    pattern found in ~50+ server tool handlers.
    """
    return _error_result(MCPVideoError(message, error_type="validation_error", code=code))


def _safe_tool(fn: Any) -> Any:
    """Decorator that wraps an MCP tool handler with standard error handling.

    Catches ``MCPVideoError`` and unexpected exceptions, returning structured
    error results via ``_error_result()``.  Preserves the original function
    signature so ``@mcp.tool()`` can introspect parameters correctly.

    Eliminates the repeated 4-line try/except wrapper found in ~85+ server
    tool handlers::

        try:
            ...
        except MCPVideoError as e:
            return _error_result(e)
        except Exception as e:
            return _error_result(e)
    """

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return await fn(*args, **kwargs)
            except MCPVideoError as e:
                return _error_result(e)
            except Exception as e:
                return _error_result(e)

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except MCPVideoError as e:
            return _error_result(e)
        except Exception as e:
            return _error_result(e)

    return wrapper


def _mcp_progress_reporter(ctx: Context | None) -> Callable[[float], None] | None:
    """Bridge a sync engine ``on_progress(percent)`` callback to MCP progress
    notifications.

    Must be called from inside an async tool (a running event loop): the engine
    invokes the callback from its stderr-reader thread, so notifications are
    scheduled with ``run_coroutine_threadsafe``. Progress reporting must never
    break a render — failures are swallowed.
    """
    if ctx is None:
        return None
    loop = asyncio.get_running_loop()

    def report(percent: float) -> None:
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(ctx.report_progress(percent, 100.0), loop)

    return report


def _error_result(err: MCPVideoError | Exception) -> dict[str, Any]:
    if isinstance(err, MCPVideoError):
        return {"success": False, "error": err.to_dict()}
    # Unexpected exception — log full traceback, return generic message
    logger.exception("Unexpected error in MCP tool handler")
    return {
        "success": False,
        "error": {
            "type": "internal_error",
            "code": "internal_error",
            "message": "An internal error occurred. Check server logs for details.",
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
