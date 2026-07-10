"""Client mixin for meta-tool discovery."""

from __future__ import annotations

from typing import Any

from ..server_tools_basic import search_tools as _search_tools


class ClientMetaMixin:
    """Mixin exposing server meta-tools to the Python Client."""

    def search_tools(self, query: str) -> dict[str, Any]:
        """Search registered MCP tools by keyword.

        Args:
            query: Search term — e.g. "blur", "resize", "subtitle", "audio", "trim".

        Returns:
            Dict with matching tools, their descriptions, and required parameters.
        """
        return _search_tools(query)
