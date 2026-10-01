"""Actual retained leader authority and portable live-supervisor controls."""

import os
import signal
import sys
import time
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError, ProcessingError
from kinocut.process_tree import ProcessTree

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX identity retention; Windows uses Job handles")


@pytest.fixture(params=[False, True], ids=["native-observation", "live-supervisor"])
def fallback(request, monkeypatch):
    import kinocut.process_observation as observation

    if not request.param and not observation.supports_nonreaping_wait():
        pytest.skip("Native WNOWAIT unavailable; live supervisor cases still run")
    if request.param:
        monkeypatch.setattr(observation, "supports_nonreaping_wait", lambda: False)
    return request.param


def test_completed_native_leader_retains_authority_until_descendants_stopped(tmp_path, fallback, monkeypatch):
    heartbeat = tmp_path / "beat"
    descendant = f"import pathlib,time; p=pathlib.Path({str(heartbeat)!r});\nwhile True:p.write_text(str(time.monotonic()));time.sleep(.02)"
    script = f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{descendant!r}],stdin=subprocess.DEVNULL);time.sleep(.1);raise SystemExit(23)"
    tree = ProcessTree([sys.executable, "-c", script])
    try:
        assert tree.wait(timeout=3) == 23
        assert tree.process.returncode is None  # Supervisor/live zombie not reaped.
        assert heartbeat.exists()
        signals, original = [], os.killpg

        def pinned_signal(pgid, sig):
            assert tree.process.returncode is None
            result = os.waitid(os.P_PID, tree.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            assert result is not None and result.si_pid == tree.process.pid
            signals.append(pgid)
            return original(pgid, sig)

        if not fallback:
            monkeypatch.setattr(os, "killpg", pinned_signal)
        else:
            monkeypatch.setattr(os, "killpg", lambda *_: pytest.fail("parent must not signal fallback numeric PID"))
        tree.close()
        assert signals == ([] if fallback else [tree.process.pid])
        assert tree.process.returncode is not None
        with pytest.raises(ChildProcessError):
            os.waitpid(tree.process.pid, os.WNOHANG)
        snapshot = heartbeat.read_bytes()
        time.sleep(0.1)
        assert heartbeat.read_bytes() == snapshot
        assert tree.wait(timeout=0) == 23
    finally:
        tree.close()
        tree.process.stdout.close()
        tree.process.stderr.close()


def test_external_kernel_reap_refuses_all_numeric_signals(fallback, monkeypatch):
    tree = ProcessTree([sys.executable, "-c", "raise SystemExit(7)"])
    assert tree.wait(timeout=3) == 7
    if fallback:
        os.kill(tree.process.pid, signal.SIGKILL)
    os.waitpid(tree.process.pid, 0)  # Raw external reap leaves Popen.returncode unset.
    assert tree.process.returncode is None
    monkeypatch.setattr(os, "killpg", lambda *_: pytest.fail("unowned reused group could be signalled"))
    try:
        with pytest.raises(MCPVideoError) as error:
            tree.close()
        assert error.value.code == "process_ownership_unavailable"
    finally:
        tree.process.stdout.close()
        tree.process.stderr.close()


@pytest.mark.parametrize("executable", ["missing-private-token", "nonexecutable-private-token"])
def test_launch_failure_is_private_typed_and_leaves_no_fds(tmp_path, fallback, executable):
    target = tmp_path / executable
    if executable.startswith("nonexecutable"):
        target.write_text("private token must not be exposed")
        target.chmod(0o600)
    before = len(list(Path("/proc/self/fd").iterdir())) if Path("/proc/self/fd").exists() else None
    with pytest.raises(ProcessingError) as error:
        ProcessTree([str(target), "secret-argument"])
    assert error.value.code == "ffmpeg_exit_-1"
    assert "private-token" not in str(error.value) and "secret-argument" not in str(error.value)
    if before is not None:
        assert len(list(Path("/proc/self/fd").iterdir())) == before


@pytest.mark.parametrize("payload", [b"", b"Cnot-an-exit-code", b"C999", b"C" + b"1" * 257])
def test_fallback_status_eof_malformed_and_oversized_are_not_success(payload):
    from kinocut.process_guardian_owner import Guardian

    guardian = Guardian.__new__(Guardian)
    guardian.status_read, writer = os.pipe()
    guardian.descriptors = {guardian.status_read}
    try:
        if payload:
            os.write(writer, payload)
        os.close(writer)
        with pytest.raises(MCPVideoError) as error:
            guardian.observe_status()
        assert error.value.code == "process_ownership_unavailable"
    finally:
        guardian.close()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_fallback_overflow_preserves_original_failure_after_safe_cleanup(fallback, stream):
    from kinocut.bounded_process import run_bounded

    descriptor = 1 if stream == "stdout" else 2
    with pytest.raises(MCPVideoError) as error:
        run_bounded(
            [sys.executable, "-c", f"import os;os.write({descriptor},b'x'*2000000)"],
            timeout=3,
            **{f"{stream}_limit": 1024},
        )
    assert error.value.code == f"command_{stream}_limit_exceeded"
