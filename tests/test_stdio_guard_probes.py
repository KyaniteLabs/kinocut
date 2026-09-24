"""Raw-stdio guard probes for the CGO-12/16 fleet defect class (2026-09-24).

These probes drive the JSON-RPC wire directly — no MCP SDK client in between,
because the SDK client normalizes away exactly the malformed shapes under test:

1. ``"params": null`` on a request (CGO-12): the server must treat null params
   as "no params" and answer normally, never crash or hang. Re-verifies
   adversarial battery 2026-09-19 criterion 2 on the current tree.
2. A UTF-8 multibyte character split across two ``write()`` calls at a byte
   boundary inside the character (CGO-16 class, first probed on kinocut): the
   server must reassemble and decode the frame as written and echo the intact
   multibyte value, never corrupt it or die.

Both probes finish with a ``ping`` round-trip proving the server survived.
"""

from __future__ import annotations

import json
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
READ_TIMEOUT = 30.0


class _RawStdioServer:
    """Minimal newline-framed JSON-RPC client over the server's real stdio."""

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_video"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert self._proc.stdin is not None and self._proc.stdout is not None

    def send_bytes(self, payload: bytes) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(payload)
        self._proc.stdin.flush()

    def send(self, request: dict[str, object]) -> None:
        self.send_bytes(json.dumps(request).encode("utf-8") + b"\n")

    def read_response(self, request_id: object) -> dict[str, object]:
        assert self._proc.stdout is not None
        deadline = time.monotonic() + READ_TIMEOUT
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self._proc.stdout], [], [], 1.0)
            if not ready:
                continue
            line = self._proc.stdout.readline()
            if not line.strip():
                continue
            message = json.loads(line.decode("utf-8"))
            if message.get("id") == request_id:
                return message
        raise TimeoutError(f"no response with id={request_id!r} within {READ_TIMEOUT}s")

    def request(self, request: dict[str, object]) -> dict[str, object]:
        request_id = request["id"]
        self.send(request)
        return self.read_response(request_id)

    def initialize(self) -> dict[str, object]:
        response = self.request(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "guard-probes", "version": "0"},
                },
            }
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return response

    def ping(self, request_id: object) -> dict[str, object]:
        return self.request({"jsonrpc": "2.0", "id": request_id, "method": "ping"})

    def close(self) -> None:
        assert self._proc.stdin is not None
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=10)


def test_null_params_is_tolerated_as_empty_params() -> None:
    # CGO-12 probe: a request whose "params" member is explicitly null must be
    # treated as "no params" — full tool list, no crash, no hang.
    server = _RawStdioServer()
    try:
        init = server.initialize()
        assert init["result"]["serverInfo"]["name"] == "kinocut"

        response = server.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": None})
        tools = response["result"]["tools"]
        assert isinstance(tools, list) and len(tools) > 100

        ping = server.ping("ping-1")
        assert "result" in ping
    finally:
        server.close()


def test_utf8_multibyte_split_across_writes_is_reassembled() -> None:
    # CGO-16-class probe: split the frame at a byte boundary INSIDE the
    # 4-byte emoji (U+1F3AC = f0 9f 8e ac, split after 2 bytes). The server
    # must decode the path exactly as written and echo it intact.
    path = "café🎬.mp4"
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "video_info",
            "arguments": {"input_path": path},
        },
    }
    frame = json.dumps(request, ensure_ascii=False).encode("utf-8")
    split_at = frame.index("🎬".encode()) + 2  # mid-character boundary

    server = _RawStdioServer()
    try:
        server.initialize()
        server.send_bytes(frame[:split_at])
        time.sleep(0.05)  # force the transport to observe a partial character
        server.send_bytes(frame[split_at:] + b"\n")

        response = server.read_response(2)
        # The file does not exist, so this must be a clean structured error —
        # and the echoed path must carry the multibyte name intact, proving
        # the split bytes were reassembled and decoded as written.
        text = json.dumps(response, ensure_ascii=False)
        assert path in text
        assert "�" not in text

        ping = server.ping("ping-2")
        assert "result" in ping
    finally:
        server.close()
