"""Actual converter/worker cancellation cleans private sources and permits retry."""

import asyncio
from pathlib import Path
import signal
import sys
import os
import pytest

from kinocut_sound.public import mix_conversion_backend, mix_conversion_prepare
from kinocut_sound.public.mix_job import render_mix_request_async
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_rate_conversion_public import converted_project  # noqa: F401


@pytest.mark.parametrize("phase", ["converter", "worker"])
def test_cancellation_reaps_owned_phase_and_removes_private_root(converted_project, monkeypatch, phase):  # noqa: F811
    root, request = converted_project
    real_args = mix_conversion_backend._conversion_args
    real_spawn = asyncio.create_subprocess_exec
    real_directory = mix_conversion_prepare.TemporaryDirectory
    directories = []
    children = []

    def directory(*args, **kwargs):
        result = real_directory(*args, **kwargs)
        directories.append(Path(result.name))
        return result

    async def spawn(*args, **kwargs):
        child = await real_spawn(*args, **kwargs)
        wanted = (phase == "converter" and any("time.sleep(10)" in value for value in args)) or (
            phase == "worker" and "kinocut_sound.public.mix_worker" in args
        )
        if wanted:
            os.kill(child.pid, signal.SIGSTOP)
            children.append(child)
        return child

    async def scenario():
        monkeypatch.setattr(mix_conversion_prepare, "TemporaryDirectory", directory)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        if phase == "converter":
            monkeypatch.setattr(
                mix_conversion_backend,
                "_conversion_args",
                lambda *args: [sys.executable, "-c", "import time; time.sleep(10)"],
            )
        task = asyncio.create_task(render_mix_request_async(request, str(root)))
        try:
            for _ in range(500):
                if children or task.done():
                    break
                await asyncio.sleep(0.01)
            assert children
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert children[0].returncode is not None
            assert all(not path.exists() for path in directories)
            assert not (root / "mix.zip").exists() and not list(root.glob(".kinocut-mix-*"))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", real_spawn)
        monkeypatch.setattr(mix_conversion_backend, "_conversion_args", real_args)
        result = await render_mix_request_async(request, str(root))
        assert result["converted_source_count"] == 2

    asyncio.run(scenario())
