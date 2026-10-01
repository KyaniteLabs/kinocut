"""Detached leased worker commands survive neither cancellation nor owner death."""

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX worker guardian; Windows uses owned Jobs")


PRELUDE = """
import concurrent.futures, fcntl, json, os, pathlib, signal, subprocess, sys, time
from kinocut.bounded_process import run_bounded
from kinocut.process_guardian_owner import bind_worker_lease
lease = open(sys.argv[1], 'a+b')
fcntl.flock(lease, fcntl.LOCK_EX)
"""


def worker(tmp_path, script, force_fallback=False):
    path = tmp_path / "worker.py"
    setup = (
        "import kinocut.process_observation as o; o.supports_nonreaping_wait = lambda: False\n"
        if force_fallback
        else ""
    )
    path.write_text(PRELUDE + setup + script)
    # This harness owns its deadline, process session and explicit stdin.
    return subprocess.Popen(
        [sys.executable, str(path), str(tmp_path / "lease")],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def finish(process):
    try:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr.decode()
        return json.loads(stdout)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


@pytest.mark.parametrize("force_fallback", [False, True])
def test_native_status_payload_fd_and_thread_scope_preserved_without_normal_orphans(tmp_path, force_fallback):
    script = """
def measure(index):
    command = [sys.executable, '-c', 'import os; print(os.getppid()); os.write(2,b"diagnostic"); raise SystemExit(23)']
    result = run_bounded(command, timeout=3)
    return [result.returncode, int(result.stdout), result.stderr, result.args == command]
with bind_worker_lease(lease.fileno()):
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(measure, range(12)))
    signals = [run_bounded([sys.executable, '-c', f'import os,signal; os.kill(os.getpid(),{s})'], timeout=3).returncode for s in (signal.SIGTERM, signal.SIGKILL)]
    with open(sys.argv[1] + '.stage', 'w+b') as stage:
        result = run_bounded([sys.executable, '-c', f'import os,sys; os.write({stage.fileno()},b"stage-data"); os.write(1,b"\\\\x00\\\\xff"); print(repr(sys.stdin.buffer.read()),file=sys.stderr)'], timeout=3, text=False, pass_fds=(stage.fileno(),))
        stage.seek(0)
        data = stage.read().decode()
    try:
        run_bounded(['/definitely/missing/kinocut-command'], timeout=3)
    except Exception as exc:
        missing = exc.code
    else:
        missing = None
    children_path = pathlib.Path(f'/proc/self/task/{os.getpid()}/children')
    children = children_path.read_text().strip() if children_path.exists() else None
print(json.dumps(dict(rows=rows, owner=os.getpid(), signals=signals, binary=result.stdout.hex(), stdin=result.stderr.decode(), stage=data, missing=missing, children=children)))
"""
    result = finish(worker(tmp_path, script, force_fallback))
    assert all(row[0] == 23 and row[1] != result["owner"] and row[2:] == ["diagnostic", True] for row in result["rows"])
    assert result["signals"] == [-signal.SIGTERM, -signal.SIGKILL]
    assert result["binary"] == "00ff"
    assert result["stdin"] == "b''\n"
    assert result["stage"] == "stage-data"
    assert result["missing"] == "ffmpeg_exit_-1"
    if result["children"] is not None:
        assert result["children"] == ""  # Native and supervisor both reaped normally.


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("Owned process fixture did not reach the expected state")


@pytest.mark.parametrize("force_fallback", [False, True])
def test_worker_sigkill_stops_native_and_grandchild_and_releases_lease(tmp_path, force_fallback):
    import fcntl

    heartbeat, native_pid, grandchild_pid = (tmp_path / name for name in ("beat", "native", "grandchild"))
    descendant = f"import os,pathlib,time; pathlib.Path({str(grandchild_pid)!r}).write_text(str(os.getpid())); p=pathlib.Path({str(heartbeat)!r});\nwhile True: p.write_text(str(time.monotonic())); time.sleep(.02)"
    command = f"import os,pathlib,subprocess,sys,time; pathlib.Path({str(native_pid)!r}).write_text(str(os.getpid())); subprocess.Popen([sys.executable,'-c',{descendant!r}],stdin=subprocess.DEVNULL); time.sleep(30)"
    process = worker(
        tmp_path,
        f"with bind_worker_lease(lease.fileno()):\n    run_bounded([sys.executable,'-c',{command!r}],timeout=40)\n",
        force_fallback,
    )
    group = None
    try:
        wait_for(lambda: heartbeat.exists() and native_pid.exists() and grandchild_pid.exists())
        native = int(native_pid.read_text())
        grandchild = int(grandchild_pid.read_text())
        group = os.getpgid(native)
        assert group != process.pid and os.getpgid(grandchild) == group
        with open(tmp_path / "lease", "a+b") as lease:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.kill(process.pid, signal.SIGKILL)
            process.wait(timeout=5)

            def lease_free():
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except BlockingIOError:
                    return False

            wait_for(lease_free)
            snapshot = heartbeat.read_bytes()
            time.sleep(0.15)
            assert heartbeat.read_bytes() == snapshot
            # On non-reaping PID1 hosts, abnormal shutdown can leave dead zombies.
            for pid in (native, grandchild, group):
                status = Path(f"/proc/{pid}/status")
                if status.exists():
                    assert "State:\tZ" in status.read_text()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        if group is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(group, signal.SIGKILL)
        for pipe in (process.stdout, process.stderr):
            pipe.close()


def test_binding_rejects_reused_lease_descriptor_and_resets_after_exit(tmp_path):
    script = """
from kinocut.errors import MCPVideoError
from kinocut.process_guardian_owner import prepare_guardian
with bind_worker_lease(lease.fileno()):
    descriptor = lease.fileno()
    with open(sys.argv[1] + '.other', 'a+b') as other:
        os.dup2(other.fileno(), descriptor)
        try:
            run_bounded([sys.executable, '-c', 'print("must not launch")'], timeout=3)
        except MCPVideoError as exc:
            code = exc.code
        else:
            code = None
from kinocut.process_guardian_owner import _WORKER_OWNER
print(json.dumps(dict(code=code, reset=_WORKER_OWNER is None)))
"""
    assert finish(worker(tmp_path, script)) == {"code": "process_ownership_unavailable", "reset": True}


def test_unleased_call_never_uses_guardian_and_invalid_worker_binding_fails():
    from kinocut.errors import MCPVideoError
    from kinocut.process_guardian_owner import bind_worker_lease, prepare_guardian

    from kinocut.process_observation import supports_nonreaping_wait

    guardian = prepare_guardian([sys.executable], ())
    if supports_nonreaping_wait():
        assert guardian is None
    else:
        assert guardian.retaining
        guardian.close()
    with pytest.raises(MCPVideoError) as error, bind_worker_lease(-1):
        pytest.fail("invalid ownership entered")
    assert error.value.code == "process_ownership_unavailable"


@pytest.mark.parametrize("payload", [b"untrusted startup data", b"X" * 257])
def test_startup_protocol_malformed_or_oversized_response_fails_closed(payload):
    from kinocut.errors import MCPVideoError
    from kinocut.process_guardian_owner import Guardian

    guardian = Guardian.__new__(Guardian)
    guardian.alive_read, guardian.alive_write = os.pipe()
    guardian.error_read, guardian.error_write = os.pipe()
    guardian.lease = os.open(os.devnull, os.O_RDONLY)
    guardian.descriptors = {
        guardian.alive_read,
        guardian.alive_write,
        guardian.error_read,
        guardian.error_write,
        guardian.lease,
    }
    guardian.native_cmd = ["not-launched"]
    guardian.status_write = -1
    try:
        os.write(guardian.error_write, payload)
        with pytest.raises(MCPVideoError) as error:
            guardian.wait_exec()
        assert error.value.code == "process_ownership_unavailable"
    finally:
        guardian.close()
    assert not guardian.descriptors


def test_retaining_supervisor_releases_streams_before_reporting_native_exit(monkeypatch):
    import select

    from kinocut import process_observation
    from kinocut.process_tree import ProcessTree

    monkeypatch.setattr(process_observation, "supports_nonreaping_wait", lambda: False)
    tree = ProcessTree(
        [sys.executable, "-c", "import os;os.write(1,b'payload');os.write(2,b'diagnostic');raise SystemExit(23)"]
    )
    try:
        assert tree.wait(timeout=1) == 23
        assert tree.process.returncode is None
        for stream, expected in ((tree.process.stdout, b"payload"), (tree.process.stderr, b"diagnostic")):
            assert select.select([stream], [], [], 1)[0]
            assert stream.read1(1024) == expected
            assert select.select([stream], [], [], 1)[0], "supervisor still holds producer pipe"
            assert stream.read1(1024) == b""
        assert tree.process.returncode is None  # Live authority retained until close.
    finally:
        tree.close()
        tree.process.stdout.close()
        tree.process.stderr.close()
    assert tree.process.returncode is not None and tree.wait(timeout=0) == 23


@pytest.mark.parametrize("inherited_writer", [False, True])
def test_retaining_supervisor_preserves_signal_reader_eof_and_descendant_deadline(
    tmp_path, monkeypatch, inherited_writer
):
    import threading

    from kinocut import process_observation, quality_signal_reader

    monkeypatch.setattr(process_observation, "supports_nonreaping_wait", lambda: False)
    monkeypatch.setattr(quality_signal_reader, "QUALITY_GUARDRAILS_TIMEOUT", 0.5)
    heartbeat = tmp_path / "descendant-beat"
    descendant = f"import pathlib,time;p=pathlib.Path({str(heartbeat)!r});\nwhile True:p.write_text(str(time.monotonic()));time.sleep(.02)"
    script = "import subprocess,sys,time;"
    if inherited_writer:
        script += f"subprocess.Popen([sys.executable,'-c',{descendant!r}],stdin=subprocess.DEVNULL);time.sleep(.1);"
    script += "print('frame:0 pts:0 pts_time:0\\nlavfi.signalstats.YAVG=37',flush=True)"
    before = {thread.ident for thread in threading.enumerate()}
    start = time.monotonic()
    if inherited_writer:
        with pytest.raises(subprocess.TimeoutExpired):
            quality_signal_reader._run_reduction(
                [sys.executable, "-c", script], quality_signal_reader.MetadataReduction()
            )
        assert heartbeat.exists()
        snapshot = heartbeat.read_bytes()
        time.sleep(0.1)
        assert heartbeat.read_bytes() == snapshot
    else:
        result = quality_signal_reader._run_reduction(
            [sys.executable, "-c", script], quality_signal_reader.MetadataReduction()
        )
        assert result.frames == 1 and result.means()["lavfi.signalstats.YAVG"] == 37
    assert time.monotonic() - start < 2
    assert {thread.ident for thread in threading.enumerate()} == before
