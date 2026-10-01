"""Post-rescue request admission rejects unsafe artifacts before dispatch."""

from __future__ import annotations

import pytest

from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_POST_RESCUE_REQUEST_BYTES
from kinocut.postrescue import load_post_rescue_request


def test_sparse_oversize_request_is_rejected(tmp_path):
    path = tmp_path / "private-request.json"
    with path.open("wb") as handle:
        handle.truncate(MAX_POST_RESCUE_REQUEST_BYTES + 1)
    with pytest.raises(MCPVideoError) as error:
        load_post_rescue_request(str(path))
    assert error.value.code == "invalid_post_rescue_request"
    assert str(path) not in str(error.value)


@pytest.mark.parametrize(
    "content",
    [b"\xff", b'{"private-fixture":', b"[" * 2000 + b"]" * 2000, b"[]"],
    ids=["utf8", "json", "depth", "nonobject"],
)
def test_malformed_or_nonobject_request_is_typed_and_redacted(tmp_path, content):
    path = tmp_path / "private-request.json"
    path.write_bytes(content)
    with pytest.raises(MCPVideoError) as error:
        load_post_rescue_request(str(path))
    assert error.value.code == "invalid_post_rescue_request"
    assert str(path) not in str(error.value)
    assert "private-fixture" not in str(error.value)


def test_valid_request_remains_compatible(tmp_path):
    path = tmp_path / "request.json"
    path.write_text('{"operation":"plan","payload":{"value":1}}', encoding="utf-8")
    assert load_post_rescue_request(str(path)) == {"operation": "plan", "payload": {"value": 1}}
