"""Real owned child cleanup on timeout and repeated cancellation."""

import asyncio
import os
from pathlib import Path
import sys

import pytest

from kinocut_sound._errors import SoundContractError
from kinocut_sound.public import asr_job
from kinocut_sound.qa.meter_process import run_meter_async, run_meter_sync
from tests.test_sound_asr_failures import fake_asr  # noqa: F401


def child_args(pid_path):
    return [
        sys.executable,
        "-c",
        "import os,time,pathlib;pathlib.Path(" + repr(str(pid_path)) + ").write_text(str(os.getpid()));time.sleep(60)",
    ]


def assert_gone(root, pid_path, workspaces):
    if pid_path.exists():
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_path.read_text()), 0)
    assert all(not path.exists() for path in workspaces)
    assert not (root / "output.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_real_asr_child_timeout(fake_asr, monkeypatch):  # noqa: F811
    root, request, _, original = fake_asr
    pid, workspaces = root / "child.pid", []
    monkeypatch.setattr(asr_job, "DEFAULT_ASR_TOTAL_TIMEOUT_SECONDS", 0.3)

    def backend(args, timeout):
        if args[-1] == "probe":
            return original(args, timeout)
        workspaces.append(Path(args[-2]).parent)
        return run_meter_sync(child_args(pid), timeout)

    monkeypatch.setattr(asr_job, "run_meter_sync", backend)
    with pytest.raises(SoundContractError):
        asr_job.recognize_sync(request, str(root))
    assert_gone(root, pid, workspaces)


def test_real_asr_child_repeated_cancel(fake_asr, monkeypatch):  # noqa: F811
    root, request, _, original = fake_asr
    pid, workspaces = root / "child.pid", []

    async def backend(args, timeout):
        if args[-1] == "probe":
            return original(args, timeout)
        workspaces.append(Path(args[-2]).parent)
        return await run_meter_async(child_args(pid), timeout)

    monkeypatch.setattr(asr_job, "run_meter_async", backend)

    async def exercise():
        task = asyncio.create_task(asr_job.recognize_async(request, str(root)))
        for _ in range(100):
            if pid.exists():
                break
            await asyncio.sleep(0.01)
        assert pid.exists()
        task.cancel()
        asyncio.get_running_loop().call_soon(task.cancel)
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert_gone(root, pid, workspaces)
