"""Actual direct children remain owned through asynchronous spawn/cleanup races."""

import asyncio
import os
import sys

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public import mix_process_async

pytestmark = pytest.mark.skipif(os.name != "posix", reason="supplied mix requires POSIX descriptors")


def test_repeated_cancellation_during_real_spawn(monkeypatch):
    original = asyncio.create_subprocess_exec

    async def scenario():
        created, release = asyncio.Event(), asyncio.Event()
        children = []

        async def delayed(*args, **kwargs):
            child = await original(*args, **kwargs)
            children.append(child)
            created.set()
            await release.wait()
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
        task = asyncio.create_task(
            mix_process_async.run_worker_async(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                b"{}",
                (),
                3,
            )
        )
        try:
            await asyncio.wait_for(created.wait(), 3)
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0.01)
                assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
            assert children[0].returncode is not None
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_timeout_during_real_spawn_still_reaps_child(monkeypatch):
    original = asyncio.create_subprocess_exec
    children = []

    async def delayed(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append(child)
        await asyncio.sleep(0.05)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed)
    with pytest.raises(MixError) as error:
        asyncio.run(
            mix_process_async.run_worker_async(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                b"{}",
                (),
                0.001,
            )
        )
    assert error.value.code == "mix_timeout"
    assert children and children[0].returncode is not None


def test_repeated_cancellation_during_cleanup(monkeypatch):
    original_cleanup = mix_process_async._cleanup

    async def scenario():
        cleaning, release = asyncio.Event(), asyncio.Event()
        children = []

        async def delayed(process, tasks=()):
            children.append(process)
            cleaning.set()
            await release.wait()
            await original_cleanup(process, tasks)

        monkeypatch.setattr(mix_process_async, "_cleanup", delayed)
        task = asyncio.create_task(
            mix_process_async.run_worker_async(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                b"{}",
                (),
                0.1,
            )
        )
        try:
            await asyncio.wait_for(cleaning.wait(), 3)
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0.01)
                assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
            assert children[0].returncode is not None
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_spawn_during_deadline_or_cancellation(monkeypatch, cancel):
    async def failing(*args, **kwargs):
        await asyncio.sleep(0.05)
        raise FileNotFoundError("missing backend")

    async def scenario():
        monkeypatch.setattr(asyncio, "create_subprocess_exec", failing)
        task = asyncio.create_task(mix_process_async.run_worker_async(["missing"], b"{}", (), 0.001))
        if cancel:
            await asyncio.sleep(0.01)
            task.cancel()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(MixError) as error:
                await task
            assert error.value.code == "mix_timeout"

    asyncio.run(scenario())
