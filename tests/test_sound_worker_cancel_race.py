"""A cancel that lands as the worker spawn finishes must not be lost (#701).

Python 3.11's asyncio.wait_for returned the inner result when cancellation
arrived after the inner future was already done, dropping the cancel. The
render then waited on the worker until its own deadline.
"""

import asyncio
import sys
import time

import pytest

from kinocut_sound.public import mix_process_async


@pytest.mark.parametrize("hops", range(6))
def test_cancel_as_spawn_completes_is_not_lost(monkeypatch, hops):
    real_spawn = asyncio.create_subprocess_exec
    children = []

    async def scenario():
        loop = asyncio.get_running_loop()
        outer = None

        def cancel_after(remaining_hops):
            if remaining_hops:
                loop.call_soon(cancel_after, remaining_hops - 1)
            else:
                outer.cancel()

        async def spawn(*args, **kwargs):
            child = await real_spawn(*args, **kwargs)
            children.append(child)
            # Land the cancel a few loop turns later, so some hop falls in the
            # window after the spawn result exists but before the caller resumes.
            loop.call_soon(cancel_after, hops)
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        outer = asyncio.create_task(mix_process_async.run_worker_async(command, b"", (), 120))
        started = time.monotonic()
        done, _ = await asyncio.wait({outer}, timeout=15)
        assert outer in done, f"cancel was lost: worker still running after {time.monotonic() - started:.0f}s"
        assert outer.cancelled()
        assert children and children[0].returncode is not None

    asyncio.run(scenario())
