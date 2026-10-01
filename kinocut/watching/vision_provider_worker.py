"""One fixed-origin HTTP exchange inside the parent's hard wall-time budget."""

from __future__ import annotations

import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from kinocut.defaults import DEFAULT_VISION_PROVIDER_TIMEOUT
from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_VISION_REQUEST_BYTES, MAX_VISION_RESPONSE_BYTES, SUBPROCESS_READ_CHUNK_BYTES

logger = logging.getLogger(__name__)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None  # Never forward credentials or media to a redirect target.


def _bounded_response(response) -> bytes:
    if response.headers.get("Content-Encoding", "identity") != "identity":
        raise MCPVideoError("Compressed vision responses are not supported", error_type="processing_error")
    length = response.headers.get("Content-Length")
    if length is not None and (not length.isdecimal() or int(length) > MAX_VISION_RESPONSE_BYTES):
        raise MCPVideoError("Vision response exceeds its byte ceiling", error_type="processing_error")
    body = bytearray()
    while chunk := response.read1(min(SUBPROCESS_READ_CHUNK_BYTES, MAX_VISION_RESPONSE_BYTES + 1 - len(body))):
        if len(body) + len(chunk) > MAX_VISION_RESPONSE_BYTES:
            raise MCPVideoError("Vision response exceeds its byte ceiling", error_type="processing_error")
        body.extend(chunk)
    if length is not None and len(body) != int(length):
        raise MCPVideoError("Vision response ended before its declared length", error_type="processing_error")
    body.decode("utf-8", errors="strict")
    return bytes(body)


def fetch_response(payload: bytes) -> bytes:
    """Read bounded successful bodies; reject redirects and close error bodies unread."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or len(payload) > MAX_VISION_REQUEST_BYTES:
        raise MCPVideoError("Vision request is unavailable or oversized", error_type="dependency_error")
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        method="POST",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "accept-encoding": "identity",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=DEFAULT_VISION_PROVIDER_TIMEOUT) as response:
            if response.status != 200:
                raise MCPVideoError("Vision provider returned a non-success status", error_type="processing_error")
            return _bounded_response(response)
    except urllib.error.HTTPError as exc:
        exc.close()  # Error bodies are not evidence and never need buffering.
        raise MCPVideoError("Vision provider returned a non-success status", error_type="processing_error") from None


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise MCPVideoError("Vision worker requires one owned request file", error_type="validation_error")
        with Path(sys.argv[1]).open("rb") as handle:
            payload = handle.read(MAX_VISION_REQUEST_BYTES + 1)
        if not payload or len(payload) > MAX_VISION_REQUEST_BYTES:
            raise MCPVideoError("Vision request exceeds its byte ceiling", error_type="validation_error")
        sys.stdout.buffer.write(fetch_response(payload))
        return 0
    except Exception as exc:
        logger.warning("Vision request failed: %s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
