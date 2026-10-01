"""JSON admission bounds allocations and rejects special files before reading."""

import json
import os
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from kinocut import json_artifacts
from kinocut.errors import MCPVideoError
from kinocut.json_artifacts import load_json_artifact, parse_json_artifact
from kinocut.limits import MAX_JSON_ARTIFACT_DEPTH


@pytest.mark.parametrize("value", [{"review": "accept"}, [{"start": 0}], None, 1])
def test_regular_file_and_inline_preserve_json_values(tmp_path, value):
    raw = json.dumps(value)
    path = tmp_path / "artifact.json"
    path.write_text(raw)
    assert load_json_artifact(path, max_bytes=len(raw)) == value
    assert parse_json_artifact(raw, max_bytes=len(raw)) == value


def test_regular_symlink_compatibility(tmp_path):
    path = tmp_path / "artifact.json"
    path.write_text("[]")
    alias = tmp_path / "alias.json"
    try:
        alias.symlink_to(path)
    except OSError:
        pytest.skip("symlink creation unavailable")
    assert load_json_artifact(alias, max_bytes=2) == []


def test_sparse_oversize_is_rejected_before_read_and_descriptor_is_closed(tmp_path, monkeypatch):
    path = tmp_path / "private-name.json"
    with path.open("wb") as handle:
        handle.truncate(1024 * 1024 + 1)
    original = json_artifacts.os.fdopen
    handles = []

    class Reader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, count):
            pytest.fail("oversized artifact reached read")

    def capture(fd, mode):
        handle = original(fd, mode)
        handles.append(handle)
        return Reader(handle)

    monkeypatch.setattr(json_artifacts.os, "fdopen", capture)
    with pytest.raises(MCPVideoError) as error:
        load_json_artifact(path, max_bytes=1024 * 1024)
    assert "byte limit" in str(error.value)
    assert "private-name" not in str(error.value)
    assert handles[0].closed


def test_growth_after_admission_read_is_cap_plus_one(tmp_path, monkeypatch):
    path = tmp_path / "grown.json"
    path.write_bytes(b" " * 100)
    original = json_artifacts.os.fdopen
    reads = []
    handles = []

    class Reader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, count):
            reads.append(count)
            return self.handle.read(count)

    def capture(fd, mode):
        handle = original(fd, mode)
        handles.append(handle)
        return Reader(handle)

    monkeypatch.setattr(json_artifacts.os, "fdopen", capture)
    monkeypatch.setattr(json_artifacts.os, "fstat", lambda fd: SimpleNamespace(st_mode=stat.S_IFREG, st_size=0))
    with pytest.raises(MCPVideoError, match="byte limit"):
        load_json_artifact(path, max_bytes=10)
    assert reads == [11]
    assert handles[0].closed


@pytest.mark.parametrize(
    "raw",
    [b"\xff", b'{"private":', b"[" * 10000 + b"]" * 10000, b"9" * 5000],
    ids=["unicode", "syntax", "recursion", "integer"],
)
def test_invalid_json_unicode_recursion_and_integer_errors_are_redacted(tmp_path, raw):
    path = tmp_path / "SECRET_FILE.json"
    path.write_bytes(raw)
    with pytest.raises(MCPVideoError) as error:
        load_json_artifact(path, max_bytes=30000, error_code="request_invalid")
    assert error.value.code == "request_invalid"
    assert "SECRET_FILE" not in str(error.value)
    assert "private" not in str(error.value)
    assert error.value.__cause__ is None


def test_inline_byte_limits_precede_json_parsing(monkeypatch):
    monkeypatch.setattr(json_artifacts.json, "loads", lambda raw: pytest.fail("oversized JSON reached parser"))
    for raw in [" " * 11, '"ééééé"']:
        with pytest.raises(MCPVideoError, match="byte limit"):
            parse_json_artifact(raw, max_bytes=10)


def test_nesting_limit_is_independent_of_interpreter_recursion_limit(monkeypatch):
    raw = "[" * MAX_JSON_ARTIFACT_DEPTH + "0" + "]" * MAX_JSON_ARTIFACT_DEPTH
    value = parse_json_artifact(raw, max_bytes=len(raw))
    for _ in range(MAX_JSON_ARTIFACT_DEPTH):
        value = value[0]
    assert value == 0
    monkeypatch.setattr(json_artifacts.json, "loads", lambda raw: pytest.fail("deep JSON reached parser"))
    with pytest.raises(MCPVideoError, match="nesting limit"):
        parse_json_artifact("[" + raw + "]", max_bytes=len(raw) + 2)


def test_quoted_braces_and_escaped_quotes_do_not_count_as_nesting():
    value = '{[}]\\"' * (MAX_JSON_ARTIFACT_DEPTH + 1)
    raw = json.dumps({"quoted": value})
    assert parse_json_artifact(raw, max_bytes=len(raw)) == {"quoted": value}


@pytest.mark.skipif(os.name != "posix", reason="FIFO/device admission uses POSIX fixtures")
def test_fifo_and_device_reject_without_blocking_and_close_descriptors(tmp_path):
    fifo = tmp_path / "artifact.fifo"
    os.mkfifo(fifo)
    script = """
import os, sys
from kinocut import json_artifacts
from kinocut.errors import MCPVideoError
original=json_artifacts.os.open
opened=[]
def capture(*args, **kwargs):
 fd=original(*args, **kwargs); opened.append(fd); return fd
json_artifacts.os.open=capture
for path in sys.argv[1:]:
 try:json_artifacts.load_json_artifact(path,max_bytes=10)
 except MCPVideoError as e:assert 'regular file' in str(e)
 else:raise AssertionError('special file accepted')
for fd in opened:
 try:os.fstat(fd)
 except OSError:pass
 else:raise AssertionError('descriptor leaked')
"""
    result = subprocess.run([sys.executable, "-c", script, str(fifo), "/dev/null"], capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr.decode()
