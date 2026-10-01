"""Safe local HTTP response objects; no external request or credentials."""

import io
import urllib.error
from types import SimpleNamespace

import pytest

from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_VISION_RESPONSE_BYTES
from kinocut.watching import vision_provider_worker as worker


class Response(io.BytesIO):
    def __init__(self, body, headers=None, status=200):
        super().__init__(body)
        self.headers = headers or {}
        self.status = status
        self.read_sizes = []

    def read1(self, size):
        self.read_sizes.append(size)
        return super().read1(size)


def test_http_body_limit_is_enforced_during_read_before_decode():
    response = Response(b"x" * (MAX_VISION_RESPONSE_BYTES + 4096))
    with pytest.raises(MCPVideoError):
        worker._bounded_response(response)
    assert response.tell() == MAX_VISION_RESPONSE_BYTES + 1
    assert max(response.read_sizes) <= MAX_VISION_RESPONSE_BYTES


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Length": str(MAX_VISION_RESPONSE_BYTES + 1)},
        {"Content-Length": "invalid"},
        {"Content-Encoding": "gzip"},
    ],
)
def test_oversized_declared_or_compressed_body_rejected_without_read(headers):
    response = Response(b"private provider response", headers)
    with pytest.raises(MCPVideoError):
        worker._bounded_response(response)
    assert not response.read_sizes


def test_http_success_uses_fixed_origin_and_no_retries_and_closes_body(monkeypatch):
    response = Response(b'{"content": []}')
    calls = []

    def open_request(request, **kwargs):
        calls.append((request, kwargs))
        return response

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-not-secret")
    monkeypatch.setattr(worker.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=open_request))
    assert worker.fetch_response(b"{}") == b'{"content": []}'
    assert response.closed
    assert len(calls) == 1
    assert calls[0][0].full_url == "https://api.anthropic.com/v1/messages"
    assert calls[0][1] == {"timeout": 60}


def test_http_error_body_is_closed_unread_and_never_reflected(monkeypatch):
    response = Response(b"private provider response" * MAX_VISION_RESPONSE_BYTES)
    error = urllib.error.HTTPError("https://api.anthropic.com/v1/messages", 429, "private reason", {}, response)

    def failed_request(*args, **kwargs):
        raise error

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-not-secret")
    monkeypatch.setattr(worker.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=failed_request))
    with pytest.raises(MCPVideoError) as failure:
        worker.fetch_response(b"{}")
    assert response.closed and not response.read_sizes
    assert "private" not in str(failure.value)


def test_redirects_never_forward_media_or_credentials():
    assert worker._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://elsewhere.invalid") is None


@pytest.mark.parametrize("body,headers", [(b"{}", {"Content-Length": "20"}), (b"\xff", {})])
def test_truncated_or_invalid_utf8_response_is_not_returned_as_valid_json(body, headers):
    with pytest.raises((MCPVideoError, UnicodeDecodeError)):
        worker._bounded_response(Response(body, headers))
