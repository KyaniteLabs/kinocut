"""Distance speech rejects invalid output and cannot publish after failures."""

import asyncio
import os
import sys
from contextlib import contextmanager
import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public import dub_bundle, dub_job, dub_spatial
from kinocut_sound.public.dub_job import render_dub_request, render_dub_request_async
from tests.test_sound_dub_render import dub_project, _require_engine  # noqa: F401
from tests.test_sound_speech_spatial_public import spatial_project  # noqa: F401


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "script",
    [
        "raise SystemExit(7)",
        "import sys; sys.stdout.buffer.write(b'\\0'*3)",
        "import os\nwhile True: os.write(1,b'x'*16384)",
    ],
)
def test_bad_effect_cannot_publish(spatial_project, monkeypatch, asynchronous, script):  # noqa: F811
    _require_engine()
    root, request = spatial_project
    monkeypatch.setattr(dub_spatial, "_args", lambda *args: [sys.executable, "-c", script])
    with pytest.raises(MixError) as error:
        if asynchronous:
            asyncio.run(render_dub_request_async(request, str(root)))
        else:
            render_dub_request(request, str(root))
    assert error.value.code == "dub_spatial_failed"
    assert not (root / "speech.zip").exists() and not list(root.glob(".kinocut-mix-*"))


def test_effect_memory_rejected_before_backend(spatial_project, monkeypatch):  # noqa: F811
    _require_engine()
    root, request = spatial_project
    monkeypatch.setattr(dub_spatial, "MAX_DUB_MEMORY_BYTES", 1)
    monkeypatch.setattr(dub_spatial, "_binary", lambda: pytest.fail("over-limit effect started backend"))
    with pytest.raises(MixError) as error:
        render_dub_request(request, str(root))
    assert error.value.code == "mix_over_limit" and not (root / "speech.zip").exists()


def test_unknown_profile_rejected_before_source_access(spatial_project, monkeypatch):  # noqa: F811
    root, request = spatial_project
    request["spatial_profile"] = "hall"
    monkeypatch.setattr(dub_job, "read_asset", lambda *args: pytest.fail("unsupported profile read source"))
    with pytest.raises(MixError):
        render_dub_request(request, str(root))
    assert not (root / "speech.zip").exists()


def test_workspace_cleanup_failure_prevents_publication(spatial_project, monkeypatch):  # noqa: F811
    _require_engine()
    root, request = spatial_project
    original = dub_job.tempfile.TemporaryDirectory

    @contextmanager
    def failing(*args, **kwargs):
        with original(*args, **kwargs) as directory:
            yield directory
        raise OSError("cleanup failure")

    monkeypatch.setattr(dub_job.tempfile, "TemporaryDirectory", failing)
    with pytest.raises(MixError):
        render_dub_request(request, str(root))
    assert not (root / "speech.zip").exists() and not list(root.glob(".kinocut-mix-*"))


def test_spatial_metadata_failure_prevents_publication(spatial_project, monkeypatch):  # noqa: F811
    _require_engine()
    root, request = spatial_project

    def fail(*args):
        raise MixError("invalid spatial metadata", code="dub_spatial_failed")

    monkeypatch.setattr(dub_bundle, "_spatial_evidence", fail)
    with pytest.raises(MixError):
        render_dub_request(request, str(root))
    assert not (root / "speech.zip").exists() and not list(root.glob(".kinocut-mix-*"))


def test_cancellation_during_effect_reaps_then_allows_retry(spatial_project, monkeypatch):  # noqa: F811
    import signal

    _require_engine()
    root, request = spatial_project
    real_args = dub_spatial._args
    real_spawn = asyncio.create_subprocess_exec
    children = []

    async def spawn(*args, **kwargs):
        child = await real_spawn(*args, **kwargs)
        if any("time.sleep(10)" in value for value in args):
            os.kill(child.pid, signal.SIGSTOP)
            children.append(child)
        return child

    async def scenario():
        monkeypatch.setattr(dub_spatial, "_args", lambda *args: [sys.executable, "-c", "import time; time.sleep(10)"])
        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        task = asyncio.create_task(render_dub_request_async(request, str(root)))
        try:
            for _ in range(500):
                if children or task.done():
                    break
                await asyncio.sleep(0.01)
            assert children
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert children[0].returncode is not None and not (root / "speech.zip").exists()
            assert not list(root.glob(".kinocut-mix-*"))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", real_spawn)
        monkeypatch.setattr(dub_spatial, "_args", real_args)
        assert (await render_dub_request_async(request, str(root)))["spatial_profile"] == "off_screen_distance"

    asyncio.run(scenario())
