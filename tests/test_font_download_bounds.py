"""Bounded, staged Google Fonts downloads with safe local network fixtures."""

from io import BytesIO
from pathlib import Path
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from kinocut import font_manager, font_download_worker as worker
from kinocut.errors import MCPVideoError

FONT = b"\x00\x01\x00\x00\x00\x01\x00\x10\x00\x00\x00\x00" + b"test\x00\x00\x00\x00\x00\x00\x00\x1c\x00\x00\x00\x04data"


class Response(BytesIO):
    def __init__(self, body=FONT, length=None):
        super().__init__(body)
        self.headers = {} if length is None else {"Content-Length": length}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    target = tmp_path / "fonts"
    monkeypatch.setattr(font_manager, "_FONT_CACHE_DIR", str(target))
    return target


def network(monkeypatch, response):
    def open_response(url, *, timeout):
        assert url.startswith("https://raw.githubusercontent.com/google/fonts/")
        assert timeout == worker.DEFAULT_FONT_DOWNLOAD_TIMEOUT
        return response

    monkeypatch.setattr(worker.urllib.request, "urlopen", open_response)
    monkeypatch.setattr(font_manager, "run_bounded", fixture_runner)


def fixture_runner(cmd, *, timeout, text, stdout_sink, stdout_limit, stderr_limit):
    """Exercise the real stream helper; real child lifetime is tested below."""
    assert cmd[:3] == [sys.executable, "-m", "kinocut.font_download_worker"]
    assert timeout == font_manager.DEFAULT_FONT_DOWNLOAD_DEADLINE
    assert text is False and stderr_limit == font_manager.MAX_FONT_DOWNLOAD_DIAGNOSTIC_BYTES
    previous = worker.MAX_FONT_DOWNLOAD_BYTES
    worker.MAX_FONT_DOWNLOAD_BYTES = stdout_limit
    try:
        worker._stream_font(cmd[-1], stdout_sink)
        return subprocess.CompletedProcess(cmd, 0, None, b"")
    except MCPVideoError as exc:
        code = worker.DOWNLOAD_OVER_LIMIT if exc.code == "font_download_over_limit" else worker.DOWNLOAD_INVALID
        return subprocess.CompletedProcess(cmd, code, None, b"font_download_invalid")
    except (URLError, OSError, TimeoutError):
        return subprocess.CompletedProcess(cmd, worker.DOWNLOAD_FAILED, None, b"font_download_failed")
    finally:
        worker.MAX_FONT_DOWNLOAD_BYTES = previous


def test_interrupted_download_never_becomes_cached_success(cache, monkeypatch):
    class Interrupted(Response):
        def read1(self, size):
            if self.tell():
                raise URLError("safe interrupted fixture")
            return super().read1(size)

    network(monkeypatch, Interrupted())
    with pytest.raises(MCPVideoError, match="Failed to download"):
        font_manager.resolve_font("roboto")
    assert not list(cache.iterdir())
    network(monkeypatch, Response())
    assert Path(font_manager.resolve_font("roboto")).read_bytes() == FONT
    assert sorted(p.name for p in cache.iterdir()) == ["roboto.ttf"]


@pytest.mark.parametrize("length", ["33", "-1", "nonsense", "9" * 21])
def test_invalid_or_incomplete_content_length_is_not_published(cache, monkeypatch, length):
    network(monkeypatch, Response(length=length))
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font("roboto")
    assert failure.value.code == "font_download_invalid"
    assert not list(cache.iterdir())


@pytest.mark.parametrize("declared", [False, True])
def test_byte_limit_is_enforced_before_file_write(cache, monkeypatch, declared):
    monkeypatch.setattr(font_manager, "MAX_FONT_DOWNLOAD_BYTES", 16)
    network(monkeypatch, Response(length="32" if declared else None))
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font("roboto")
    assert failure.value.code == "font_download_over_limit"
    assert not list(cache.iterdir())


@pytest.mark.parametrize("body", [b"", b"HTML error page", b"OTTO"])
def test_invalid_font_header_is_not_cached(cache, monkeypatch, body):
    network(monkeypatch, Response(body))
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font("roboto")
    assert failure.value.code == "font_download_invalid"
    assert not list(cache.iterdir())


def test_elapsed_deadline_rejects_before_publication(cache, monkeypatch):
    ticks = iter([0, 0, 0, worker.DEFAULT_FONT_DOWNLOAD_DEADLINE + 1])
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    network(monkeypatch, Response())
    with pytest.raises(MCPVideoError, match="Failed to download"):
        font_manager.resolve_font("roboto")
    assert not list(cache.iterdir())


def test_corrupt_old_cache_is_replaced_only_after_success(cache, monkeypatch):
    cache.mkdir()
    target = cache / "roboto.ttf"
    target.write_bytes(b"old interrupted download")
    network(monkeypatch, Response(b"bad"))
    with pytest.raises(MCPVideoError):
        font_manager.resolve_font("roboto")
    assert target.read_bytes() == b"old interrupted download"
    network(monkeypatch, Response(length=str(len(FONT))))
    assert Path(font_manager.resolve_font("roboto")).read_bytes() == FONT


def test_cache_symlink_never_writes_referent(cache, tmp_path, monkeypatch):
    cache.mkdir()
    outside = tmp_path / "outside.ttf"
    outside.write_bytes(FONT)
    try:
        (cache / "roboto.ttf").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    network(monkeypatch, Response())
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font("roboto")
    assert failure.value.code == "unsafe_path"
    assert outside.read_bytes() == FONT


@pytest.mark.parametrize("value", [None, True, 123, "", " " * 4097, "r" * 4097])
def test_font_identifier_validation(value):
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font(value)
    assert failure.value.code == "invalid_font"


def substitute_child(monkeypatch, code):
    real_runner = font_manager.run_bounded

    def run_fixture(cmd, **kwargs):
        assert cmd[-1] == "roboto"
        return real_runner([sys.executable, "-c", code], **kwargs)

    monkeypatch.setattr(font_manager, "run_bounded", run_fixture)


def test_actual_child_hang_is_killed_by_parent_elapsed_deadline(cache, monkeypatch):
    substitute_child(monkeypatch, "import time; time.sleep(60)")
    monkeypatch.setattr(font_manager, "DEFAULT_FONT_DOWNLOAD_DEADLINE", 0.2)
    started = time.monotonic()
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font("roboto")
    assert failure.value.code == "font_download_failed"
    assert time.monotonic() - started < 3
    assert not list(cache.iterdir())


def test_actual_child_stdout_byte_limit_prevents_publication(cache, monkeypatch):
    substitute_child(monkeypatch, "import sys; sys.stdout.buffer.write(b'x' * 65536)")
    monkeypatch.setattr(font_manager, "MAX_FONT_DOWNLOAD_BYTES", 16)
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font("roboto")
    assert failure.value.code == "font_download_over_limit"
    assert not list(cache.iterdir())


def test_actual_child_stderr_byte_limit_is_bounded_failure(cache, monkeypatch):
    substitute_child(monkeypatch, "import sys; sys.stderr.buffer.write(b'private-network-content' * 4096)")
    monkeypatch.setattr(font_manager, "MAX_FONT_DOWNLOAD_DIAGNOSTIC_BYTES", 16)
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font("roboto")
    assert failure.value.code == "font_download_failed"
    assert "private-network-content" not in str(failure.value)
    assert not list(cache.iterdir())


def test_actual_child_valid_font_bytes_are_validated_and_published(cache, monkeypatch):
    substitute_child(monkeypatch, f"import sys; sys.stdout.buffer.write({FONT!r})")
    assert Path(font_manager.resolve_font("roboto")).read_bytes() == FONT
    assert [p.name for p in cache.iterdir()] == ["roboto.ttf"]


def test_actual_child_malformed_font_is_not_published(cache, monkeypatch):
    substitute_child(monkeypatch, "import sys; sys.stdout.buffer.write(b'OTTO')")
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font("roboto")
    assert failure.value.code == "font_download_invalid"
    assert not list(cache.iterdir())


def test_worker_cli_rejects_caller_urls_and_paths():
    result = subprocess.run(
        [sys.executable, "-m", "kinocut.font_download_worker", "http://127.0.0.1:9/font"],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == worker.DOWNLOAD_INVALID
    assert result.stdout == b""
    assert result.stderr == b"font_download_invalid" + os.linesep.encode("ascii")


def test_actual_network_trickle_is_bounded_and_never_published(cache, monkeypatch):
    import http.server
    import threading

    class Slow(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(FONT)))
            self.end_headers()
            try:
                for byte in FONT:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.025)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Endpoint mutation exists only in this spawned test fixture, never in
        # the product CLI. Run the shipped worker's exact network read path.
        code = (
            "from kinocut import font_download_worker as w; "
            f"w._GOOGLE_FONT_URLS['roboto']='http://127.0.0.1:{server.server_port}/font'; "
            "w.DEFAULT_FONT_DOWNLOAD_DEADLINE=0.15; w.DEFAULT_FONT_DOWNLOAD_TIMEOUT=0.1; "
            "raise SystemExit(w.main(['roboto']))"
        )
        substitute_child(monkeypatch, code)
        monkeypatch.setattr(font_manager, "DEFAULT_FONT_DOWNLOAD_DEADLINE", 0.4)
        started = time.monotonic()
        with pytest.raises(MCPVideoError) as failure:
            font_manager.resolve_font("roboto")
        assert failure.value.code == "font_download_failed"
        assert time.monotonic() - started < 3
        assert not list(cache.iterdir())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_worker_unexpected_error_does_not_echo_network_content():
    code = (
        "from kinocut import font_download_worker as w; "
        "w._stream_font=lambda *args: (_ for _ in ()).throw(ValueError('private-network-content')); "
        "raise SystemExit(w.main(['roboto']))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=5, check=False)
    assert result.returncode == worker.DOWNLOAD_FAILED
    assert result.stdout == b""
    assert b"font_download_failed" in result.stderr
    assert b"private-network-content" not in result.stderr
    assert b"Traceback" not in result.stderr


def test_child_writes_owned_descriptor_when_stage_name_is_replaced(cache, tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("POSIX permits renaming an open staging inode")
    outside = tmp_path / "outside.ttf"
    outside.write_bytes(b"outside bytes must remain unchanged")
    real_runner = font_manager.run_bounded

    def race_stage(cmd, **kwargs):
        stage = next(cache.glob(".kinocut_tmp_*"))
        stage.unlink()
        stage.symlink_to(outside)
        return real_runner([sys.executable, "-c", f"import sys; sys.stdout.buffer.write({FONT!r})"], **kwargs)

    monkeypatch.setattr(font_manager, "run_bounded", race_stage)
    with pytest.raises(MCPVideoError) as failure:
        font_manager.resolve_font("roboto")
    assert failure.value.code == "unsafe_path"
    assert outside.read_bytes() == b"outside bytes must remain unchanged"
    assert not (cache / "roboto.ttf").exists()
