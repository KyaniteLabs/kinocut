"""Actual child cleanup and bounded streaming under hostile meter behavior."""

import asyncio
import os
import signal
import subprocess
import sys
import time

import pytest

from kinocut_sound.qa import QaError
from kinocut_sound.qa import meter_process


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "script,code",
    [
        ("import os\nwhile True: os.write(1,b'x'*8192)", "qa_meter_over_limit"),
        ("import time;time.sleep(30)", "qa_meter_timeout"),
        ("print('SUCCESS');raise SystemExit(1)", "qa_meter_failed"),
        ("print('No such filter: ebur128');raise SystemExit(1)", "qa_unavailable"),
    ],
)
def test_real_meter_failure_kills_and_reaps(monkeypatch, asynchronous, script, code):
    processes = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", capture)
    args = [sys.executable, "-c", script]
    start = time.monotonic()
    with pytest.raises(QaError) as failure:
        if asynchronous:
            asyncio.run(meter_process.run_meter_async(args, 0.3))
        else:
            meter_process.run_meter_sync(args, 0.3)
    assert failure.value.code == code
    assert time.monotonic() - start < 5
    assert processes
    assert all(p.poll() is not None for p in processes)


def test_repeated_sync_interrupts_still_reap(monkeypatch):
    original = subprocess.Popen
    processes = []

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        wait = process.wait
        attempts = 0

        def interrupted(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts <= 2:
                raise KeyboardInterrupt
            return wait(*args, **kwargs)

        process.wait = interrupted
        return process

    monkeypatch.setattr(subprocess, "Popen", capture)
    with pytest.raises(KeyboardInterrupt):
        meter_process.run_meter_sync([sys.executable, "-c", "import time;time.sleep(30)"], 1)
    assert processes[0].poll() is not None


def test_repeated_async_cancel_waits_for_reap(monkeypatch):
    if not hasattr(signal, "SIGSTOP"):
        pytest.skip("stopped-child cancellation fixture needs POSIX signals")

    async def scenario():
        started, waiting, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = asyncio.create_subprocess_exec
        children = []

        async def stopped(*args, **kwargs):
            process = await original(*args, **kwargs)
            children.append(process)
            os.kill(process.pid, signal.SIGSTOP)
            wait = process.wait

            async def delayed():
                waiting.set()
                await release.wait()
                return await wait()

            process.wait = delayed
            started.set()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", stopped)
        task = asyncio.create_task(meter_process.run_meter_async([sys.executable, "-c", "pass"], 2))
        try:
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            await asyncio.wait_for(waiting.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(ProcessLookupError):
                os.kill(children[0].pid, 0)
        finally:
            release.set()
            for process in children:
                if process.returncode is None:
                    process.kill()
                await process.wait()

    asyncio.run(asyncio.wait_for(scenario(), 5))
