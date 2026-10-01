"""Real owned children exercise stream budgets, exit errors and cleanup."""

import os
import subprocess
import sys
import threading

import pytest

from kinocut.errors import MCPVideoError, ProcessingError
from kinocut import quality_signal_reader as reader


@pytest.fixture
def child(tmp_path, monkeypatch):
    script = tmp_path / "probe.py"
    monkeypatch.setattr(reader, "_ffprobe", lambda: sys.executable)

    def run(source, **kwargs):
        script.write_text(source)
        return reader.read_signalstats(["ffprobe", str(script), "-of", "json"], **kwargs)

    return run


def test_streamed_frames_preserve_range_and_compensated_means(child):
    result = child(
        "print('pix_fmt=yuv420p10le|color_range=tv|color_transfer=smpte2084|tag:lavfi.signalstats.YAVG=400')\n"
        "print('pix_fmt=yuv420p|color_range=tv|tag:lavfi.signalstats.YAVG=120')",
        retain_values=True,
    )
    assert result.frames == 2
    assert result.hdr
    assert result.means()["lavfi.signalstats.YAVG"] == 110
    assert list(result.values["lavfi.signalstats.YAVG"]) == [100, 120]


@pytest.mark.parametrize(
    "budget,source",
    [
        ("MAX_QUALITY_SIGNALSTATS_LINE_BYTES", "print('x' * 100)"),
        ("MAX_QUALITY_SIGNALSTATS_OUTPUT_BYTES", "print('tag:lavfi.signalstats.YAVG=120')"),
        ("MAX_QUALITY_SIGNALSTATS_DIAGNOSTIC_BYTES", "import sys; sys.stderr.write('x' * 100)"),
        ("MAX_QUALITY_SIGNALSTATS_FRAMES", "print('tag:lavfi.signalstats.YAVG=120\\n' * 2)"),
    ],
)
def test_budget_overflow_fails_instead_of_returning_partial(child, monkeypatch, budget, source):
    monkeypatch.setattr(reader, budget, 1 if budget.endswith("FRAMES") else 20)
    with pytest.raises(MCPVideoError, match="budget exceeded"):
        child(source)


def test_failed_child_does_not_return_its_partial_valid_measurement(child):
    with pytest.raises(ProcessingError):
        child("import sys; print('tag:lavfi.signalstats.YAVG=120'); sys.exit(7)")


def test_timeout_reaps_child_and_both_readers(child, tmp_path, monkeypatch):
    pid = tmp_path / "pid"
    before = {t.ident for t in threading.enumerate()}
    spawned = []
    original_popen = reader.subprocess.Popen

    def capture_process(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(reader.subprocess, "Popen", capture_process)
    monkeypatch.setattr(reader, "QUALITY_GUARDRAILS_TIMEOUT", 0.1)
    with pytest.raises(subprocess.TimeoutExpired):
        child(f"import os,time; open({str(pid)!r}, 'w').write(str(os.getpid())); time.sleep(30)")
    assert len(spawned) == 1
    process = spawned[0]
    assert process.pid == int(pid.read_text())
    # Inspect before poll: the reader must have reaped it, not this assertion.
    assert process.returncode is not None and process.returncode != 0
    assert process.poll() == process.returncode
    assert process.stdout.closed and process.stderr.closed
    if os.name == "posix":
        with pytest.raises(ProcessLookupError):
            os.kill(process.pid, 0)
    assert {t.ident for t in threading.enumerate()} == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX group cleanup")
def test_exited_parent_with_inherited_pipe_writers_obeys_deadline(child, monkeypatch):
    monkeypatch.setattr(reader, "QUALITY_GUARDRAILS_TIMEOUT", 0.1)
    with pytest.raises(subprocess.TimeoutExpired):
        child("import subprocess,sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])")


def test_fallback_reduction_flushes_final_frame_and_rejects_unknown_fields():
    result = reader.MetadataReduction()
    for line in (
        b"frame:0 pts:0 pts_time:0\n",
        b"lavfi.signalstats.YAVG=20\n",
        b"frame:1 pts:1\n",
        b"lavfi.signalstats.YAVG=40\n",
    ):
        result.consume(line)
    result.finish()
    assert result.frames == 2
    assert result.means()["lavfi.signalstats.YAVG"] == 30
    with pytest.raises(MCPVideoError):
        result.consume(b"arbitrary=value")


def test_repeated_keyboard_interrupt_still_reaps_child_and_readers(child, monkeypatch):
    from kinocut.process_tree import ProcessTree

    original = ProcessTree.wait
    interruptions = 0
    before = {t.ident for t in threading.enumerate()}

    def wait(process, *args, **kwargs):
        nonlocal interruptions
        if interruptions < 2:
            interruptions += 1
            raise KeyboardInterrupt
        return original(process, *args, **kwargs)

    monkeypatch.setattr(ProcessTree, "wait", wait)
    original_reap = reader.subprocess.Popen.wait

    def reap(process, *args, **kwargs):
        nonlocal interruptions
        if interruptions < 2:
            interruptions += 1
            raise KeyboardInterrupt
        return original_reap(process, *args, **kwargs)

    monkeypatch.setattr(reader.subprocess.Popen, "wait", reap)
    with pytest.raises(KeyboardInterrupt):
        child("import time; time.sleep(30)")
    assert interruptions == 2
    assert {t.ident for t in threading.enumerate()} == before


@pytest.mark.parametrize(
    "source", ["import sys;sys.stdout.buffer.write(b'\\xff')", "print('arbitrary=value')", "print('missing_equals')"]
)
def test_malformed_measurements_raise_bounded_custom_error(child, source):
    with pytest.raises(MCPVideoError) as failure:
        child(source)
    assert failure.value.code == "analysis_invalid_output"


def test_windows_pipe_polling_is_cancellable_without_waiting_for_inherited_writer(monkeypatch):
    from kinocut import quality_signal_windows as windows

    stop = threading.Event()
    waiting = threading.Event()

    def available(_pipe):
        waiting.set()
        return 0  # Writer remains open, so neither data nor EOF is available.

    monkeypatch.setattr(windows, "_available_bytes", available)
    collected = []
    thread = threading.Thread(target=lambda: collected.extend(windows.lines(None, stop)))
    thread.start()
    assert waiting.wait(1)
    stop.set()
    thread.join(1)
    assert not thread.is_alive()
    assert collected == []


def test_windows_pipe_polling_handles_split_lines_and_unterminated_eof(monkeypatch):
    from kinocut import quality_signal_windows as windows

    ready = iter([3, 4, -1])
    content = iter([b"one", b"\ntwo"])
    monkeypatch.setattr(windows, "_available_bytes", lambda _pipe: next(ready))
    monkeypatch.setattr(windows.os, "read", lambda *_: next(content))
    pipe = type("Pipe", (), {"fileno": lambda self: 7})()
    assert list(windows.lines(pipe, threading.Event())) == [b"one\n", b"two"]


@pytest.mark.skipif(os.name != "posix" or not os.path.isdir("/proc"), reason="Linux process state proof")
def test_inherited_writer_process_group_is_terminated(child, tmp_path, monkeypatch):
    from pathlib import Path
    import time

    descendant = tmp_path / "descendant.pid"
    source = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {('import os,time;open(' + repr(str(descendant)) + ', chr(119)).write(str(os.getpid()));time.sleep(30)')!r}]); "
        "time.sleep(.1)"
    )
    monkeypatch.setattr(reader, "QUALITY_GUARDRAILS_TIMEOUT", 1)
    with pytest.raises(subprocess.TimeoutExpired):
        child(source)
    assert descendant.exists()
    status = Path("/proc") / descendant.read_text() / "status"
    # The direct child is reaped; an orphan may await the host's init reaper.
    deadline = time.monotonic() + 5
    while status.exists():
        try:
            state = status.read_text()
        except FileNotFoundError:
            break
        if "State:\tZ" in state:
            break
        assert time.monotonic() < deadline, state
        time.sleep(0.01)
