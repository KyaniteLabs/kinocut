"""Real subprocess resource and inherited-pipe lifecycle controls."""

import io
import os
import subprocess
import sys
import threading
import time

import pytest

from kinocut.bounded_process import run_bounded
from kinocut.errors import MCPVideoError


def command(script):
    return [sys.executable, "-c", script]


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_byte_overflow_is_failure_and_sink_never_exceeds_budget(stream):
    sink = io.BytesIO()
    kwargs = {f"{stream}_limit": 1024, f"{stream}_sink": sink}
    before = {thread.ident for thread in threading.enumerate()}
    with pytest.raises(MCPVideoError) as error:
        run_bounded(
            command(f"import os; os.write({1 if stream == 'stdout' else 2}, b'x'*2000000)"), timeout=3, **kwargs
        )
    assert error.value.code == f"command_{stream}_limit_exceeded"
    assert len(sink.getvalue()) <= 1024
    assert {thread.ident for thread in threading.enumerate()} == before


def test_concurrent_exact_budget_preserves_payload_exit_code_and_utf8():
    script = "import os; os.write(1,b'a'*100000); os.write(2,b'\\xff'*100000); raise SystemExit(23)"
    result = run_bounded(command(script), timeout=3, stdout_limit=100000, stderr_limit=100000)
    assert result.returncode == 23
    assert result.stdout == "a" * 100000
    assert result.stderr == "\ufffd" * 100000


def test_sink_flush_and_binary_output_contract():
    with io.BytesIO() as sink:
        result = run_bounded(command("import os; os.write(1,b'\\x00\\xff')"), timeout=3, text=False, stdout_sink=sink)
        assert result.stdout is None
        assert sink.getvalue() == b"\x00\xff"
    result = run_bounded(command("import os; os.write(1,b'\\x00\\xff')"), timeout=3, text=False)
    assert result.stdout == b"\x00\xff"


@pytest.mark.parametrize("leader_exits", [False, True])
def test_descendant_inherited_pipes_cannot_outlive_command(tmp_path, leader_exits):
    heartbeat = tmp_path / "heartbeat"
    child = (
        "import pathlib,time; p=pathlib.Path("
        + repr(str(heartbeat))
        + ");\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.02)"
    )
    script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(.2); "
    script += "raise SystemExit(0)" if leader_exits else "time.sleep(20)"
    start = time.monotonic()
    if leader_exits:
        assert run_bounded(command(script), timeout=3).returncode == 0
    else:
        with pytest.raises(subprocess.TimeoutExpired):
            run_bounded(command(script), timeout=0.5)
    assert time.monotonic() - start < 3
    assert heartbeat.exists()
    snapshot = heartbeat.read_bytes()
    time.sleep(0.1)
    assert heartbeat.read_bytes() == snapshot


def test_owned_child_stdin_is_eof():
    result = run_bounded(command("import sys; print(repr(sys.stdin.buffer.read()))"), timeout=3)
    assert result.stdout.strip() == "b''"


def test_streamed_no_newline_flood_is_memory_bounded_before_disk_write():
    import tempfile
    import tracemalloc

    with tempfile.TemporaryFile() as sink:
        tracemalloc.start()
        try:
            with pytest.raises(MCPVideoError) as error:
                run_bounded(
                    command("import os\nwhile True: os.write(1,b'x'*65536)"),
                    timeout=3,
                    stdout_sink=sink,
                    stdout_limit=524288,
                )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert error.value.code == "command_stdout_limit_exceeded"
        sink.flush()
        assert 0 < os.fstat(sink.fileno()).st_size <= 524288
        assert peak < 2_000_000


def test_cancellation_reaps_before_propagating_and_closes_both_pipes(monkeypatch):
    original = subprocess.Popen
    processes = []

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    from kinocut.process_tree import ProcessTree

    monkeypatch.setattr(subprocess, "Popen", spawn)
    monkeypatch.setattr(ProcessTree, "wait", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt("cancelled")))
    with pytest.raises(KeyboardInterrupt):
        run_bounded(command("import time;time.sleep(30)"), timeout=3)
    assert processes[0].returncode is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed


@pytest.mark.parametrize("reported", [None, True, False, 0, -1, 1.5, "1", 999])
def test_sink_rejects_invalid_write_counts_without_false_success(reported):
    class InvalidSink:
        def write(self, chunk):
            return reported

        def flush(self):
            pass

    with pytest.raises(MCPVideoError) as error:
        run_bounded(command("import os;os.write(1,b'abc')"), timeout=3, stdout_sink=InvalidSink())
    assert error.value.code == "command_sink_failed"


def test_sink_completes_legitimate_partial_writes():
    class PartialSink(io.BytesIO):
        def write(self, chunk):
            return super().write(chunk[:1])

    sink = PartialSink()
    result = run_bounded(command("import os;os.write(1,b'abcdef')"), timeout=3, stdout_sink=sink)
    assert result.returncode == 0 and result.stdout is None
    assert sink.getvalue() == b"abcdef"
