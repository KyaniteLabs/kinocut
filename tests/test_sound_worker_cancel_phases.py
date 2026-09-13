"""Repeated cancellation at real write, discard and final-wait seams."""

import asyncio
import os
import sys
import pytest

from kinocut_sound.public import mix_process_async

pytestmark = pytest.mark.skipif(os.name != "posix", reason="supplied mix requires POSIX descriptors")


def install_controls(phase, monkeypatch, started, release, children):
    real_spawn = asyncio.create_subprocess_exec
    real_write = mix_process_async._write
    real_discard = mix_process_async._discard

    async def spawn(*args, **kwargs):
        child = await real_spawn(*args, **kwargs)
        children.append(child)
        if phase == "wait":
            original = child.wait
            calls = 0

            async def wait():
                nonlocal calls
                calls += 1
                if calls > 1:
                    started.set()
                    await release.wait()
                return await original()

            child.wait = wait
        return child

    async def write(stream, encoded):
        started.set()
        return await real_write(stream, encoded)

    async def discard(stream):
        started.set()
        await release.wait()
        return await real_discard(stream)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    if phase == "stdin":
        monkeypatch.setattr(mix_process_async, "_write", write)
    elif phase == "drain":
        monkeypatch.setattr(mix_process_async, "_discard", discard)


@pytest.mark.parametrize("phase", ["stdin", "drain", "wait"])
def test_cancellation_at_each_owned_phase(monkeypatch, phase):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        children = []
        install_controls(phase, monkeypatch, started, release, children)
        script = {
            "stdin": "import time; time.sleep(10)",
            "drain": "import os\nwhile True: os.write(1,b'x'*16384)",
            "wait": "pass",
        }[phase]
        task = asyncio.create_task(
            mix_process_async.run_worker_async(
                [sys.executable, "-c", script],
                b"x" * 1_000_000,
                (),
                3,
            )
        )
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            if phase != "stdin":
                for _ in range(3):
                    await asyncio.sleep(0.01)
                    task.cancel()
                    assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
            assert children and children[0].returncode is not None
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())
