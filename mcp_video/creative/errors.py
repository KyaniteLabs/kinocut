"""Stable errors for pure creative planning contracts."""

from __future__ import annotations

from mcp_video.errors import MCPVideoError


class CreativeContractError(MCPVideoError):
    """A creative artifact or declared evidence violates its contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, error_type="creative_contract_error", code=code)
