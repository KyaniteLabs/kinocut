"""Minimal MCP stdio client for the compat-matrix harness.

Speaks newline-delimited JSON-RPC 2.0 against the SAME MCP server the
``kino`` CLI exposes (``python -m kinocut --mcp``) — the harness never uses
a bespoke API (COMPAT-MATRIX-SPEC.md "How a model drives the MCP surface").

Build order 1 scope: initialize handshake, tools/list with manifest-byte
accounting, and tools/call. No cloud anything: the client dials only the
in-repo stdio server (agent-mode chat endpoints are wired at build order 2).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "kinocut-compat-matrix", "version": "0.1.0"}


class MCPClientError(RuntimeError):
    """Raised on transport or protocol failures."""


@dataclass
class MCPHandshake:
    server_name: str
    server_version: str
    protocol_version: str
    tools_count: int = 0
    manifest_bytes: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


class MCPStdioClient:
    """JSON-RPC 2.0 client over the server process's stdin/stdout pipes."""

    def __init__(self, command: list[str], cwd: str | None = None, timeout: float = 60.0):
        self.command = command
        self.cwd = cwd
        self.timeout = timeout
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        if self._proc is not None:
            raise MCPClientError("client already started")
        self._proc = subprocess.Popen(  # noqa: S603 - repo-owned kino MCP server
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def close(self) -> None:
        if self._proc is None:
            return
        proc, self._proc = self._proc, None
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def __enter__(self) -> MCPStdioClient:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- transport -----------------------------------------------------
    def _send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPClientError("client not started")
        line = json.dumps(payload, separators=(",", ":"))
        if "\n" in line:  # MCP stdio law: no embedded newlines
            raise MCPClientError("payload contains embedded newline")
        self._proc.stdin.write(line + "\n")
        self._proc.stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        if self._proc is None or self._proc.stdout is None:
            raise MCPClientError("client not started")
        import time

        deadline = time.monotonic() + self.timeout
        while True:
            if time.monotonic() > deadline:
                raise MCPClientError("timeout waiting for server message")
            line = self._proc.stdout.readline()
            if not line:
                raise MCPClientError("server closed stdout")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                raise MCPClientError(f"non-JSON line from server: {line[:120]!r}") from exc
            if isinstance(msg, dict):
                return msg

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        req_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
        while True:
            msg = self._read_message()
            if msg.get("id") != req_id or ("result" not in msg and "error" not in msg):
                continue  # notification or unrelated traffic
            if "error" in msg:
                raise MCPClientError(f"{method} error: {msg['error']}")
            result = msg["result"]
            return result if isinstance(result, dict) else {"value": result}

    def _notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    # -- MCP surface ---------------------------------------------------
    def initialize(self) -> dict[str, Any]:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        self._notify("notifications/initialized")
        return result

    def list_tools(self) -> tuple[list[dict[str, Any]], int]:
        result = self._request("tools/list")
        tools = result.get("tools", [])
        manifest_bytes = len(json.dumps(tools, separators=(",", ":")).encode("utf-8"))
        return tools, manifest_bytes

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def handshake(self) -> MCPHandshake:
        init = self.initialize()
        server_info = init.get("serverInfo", {})
        tools, manifest_bytes = self.list_tools()
        return MCPHandshake(
            server_name=str(server_info.get("name", "?")),
            server_version=str(server_info.get("version", "?")),
            protocol_version=str(init.get("protocolVersion", PROTOCOL_VERSION)),
            tools_count=len(tools),
            manifest_bytes=manifest_bytes,
            raw=init,
        )
