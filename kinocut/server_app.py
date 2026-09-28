"""Shared FastMCP app and result helpers."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
from collections.abc import Callable
from importlib import metadata as _importlib_metadata
from typing import Any

import mcp.server.fastmcp.server as _fastmcp_server
from mcp.server.fastmcp import Context, FastMCP

from .errors import MCPVideoError

# MCP 1.29 leaves Settings.lifespan as a forward reference. Rebuild it after the
# module is loaded so pydantic-settings 2.15 cannot emit warnings into JSON CLI stderr.
_fastmcp_server.Settings.model_rebuild(_types_namespace=vars(_fastmcp_server))


def _product_version() -> str:
    """Return the real kinocut version for the MCP handshake.

    Prefers installed package metadata (the dist-info a user actually
    installed) and falls back to the source-tree ``__version__`` for
    uninstalled checkouts. Without this, ``FastMCP`` reports the underlying
    MCP SDK version as ``serverInfo.version``, so clients and store listings
    cannot see which kinocut release they are talking to.
    """
    try:
        return _importlib_metadata.version("kinocut")
    except _importlib_metadata.PackageNotFoundError:
        from . import __version__ as _source_version

        return _source_version


mcp = FastMCP(
    "kinocut",
    instructions=(
        "Kinocut is a video editing MCP server. Default path: inspect (info/doctor) → "
        "plan (video_intent or cutfile) → render → quality check → human review. "
        "Do not publish without QC and a human gate. Prefer video_intent verbs over "
        "listing every tool. Paths should be absolute. Output is auto-generated if omitted."
    ),
)

# FastMCP (mcp>=1.27,<2) does not forward a version to the lowlevel Server, so
# the handshake would report the MCP SDK's own version (e.g. "1.30.0") as
# serverInfo.version. The lowlevel Server reads ``version`` at connect time
# via ``create_initialization_options()``, so setting it here makes every
# client see the real kinocut release. The handshake test in tests/test_server.py
# guards this against SDK changes.
_lowlevel_server = getattr(mcp, "_mcp_server", None)
if _lowlevel_server is not None:
    _lowlevel_server.version = _product_version()

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
