"""In-process fake ``/v1/systemone`` server for CI-safe end-to-end tests."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _FakeHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length))
            criteria = body["questions"]["operation"]["criteria"]
        except (KeyError, TypeError, ValueError):
            self.send_error(400)
            return
        candidates = [name for name in criteria if name != "unsure"]
        if not candidates:
            self.send_error(400)
            return
        choice = candidates[0]
        probabilities = {name: round(1.0 / len(candidates), 6) for name in candidates}
        probabilities[choice] = round(1.0 - sum(probabilities.values()) + probabilities[choice], 6)
        payload = json.dumps(
            {"operation": {"choice": choice, "probabilities": probabilities, "confidence": probabilities[choice]}}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


@contextmanager
def serve_fake() -> Iterator[str]:
    """Serve the fake endpoint on a loopback port and yield its base URL."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
