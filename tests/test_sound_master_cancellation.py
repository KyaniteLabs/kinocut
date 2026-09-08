"""Job cancellation and total timeout reap their direct child and remove staging."""

import asyncio
import json
import os
from pathlib import Path
import sys

import pytest

from kinocut_sound._errors import SoundContractError
from kinocut_sound.public import master_job
from tests.test_sound_master_public import master_project  # noqa: F401 - shared fixture


def sleeping_engine(root):
    script = root / "fake-ffmpeg"
    state = root / "child.json"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json,os,sys,time\nfrom pathlib import Path\n"
        "if '-version' in sys.argv:\n print('ffmpeg version test-1.0');sys.exit(0)\n"
        f"Path({str(state)!r}).write_text(json.dumps({{'pid':os.getpid(),'source':sys.argv[sys.argv.index('-i')+1]}}))\n"
        "time.sleep(30)\n"
    )
    script.chmod(0o700)
    return script, state


def assert_clean(root, state):
    child = json.loads(state.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child["pid"], 0)
    assert not Path(child["source"]).parent.exists()
    assert not (root / "master.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


def test_whole_job_timeout_cleans_child_and_stage(master_project, monkeypatch):  # noqa: F811
    root, request = master_project
    script, state = sleeping_engine(root)
    monkeypatch.setattr(master_job.shutil, "which", lambda _: str(script))
    monkeypatch.setattr(master_job, "DEFAULT_MASTER_TOTAL_TIMEOUT_SECONDS", 1)
    with pytest.raises(SoundContractError) as failure:
        master_job.render_master_request(request, str(root))
    assert failure.value.code in {"qa_meter_timeout", "master_timeout"}
    assert_clean(root, state)


def test_repeated_async_cancel_cleans_child_and_stage(master_project, monkeypatch):  # noqa: F811
    root, request = master_project
    script, state = sleeping_engine(root)
    monkeypatch.setattr(master_job.shutil, "which", lambda _: str(script))

    async def exercise():
        task = asyncio.create_task(master_job.render_master_request_async(request, str(root)))
        try:
            async with asyncio.timeout(5):
                while not state.exists():
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())
    assert_clean(root, state)
