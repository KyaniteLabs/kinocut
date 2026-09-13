"""Real worker pipe limits, with the normal public status decoder retained."""

import asyncio
import json
import os
import subprocess
import sys

import pytest

from kinocut_sound.limits import MAX_MIX_WORKER_MESSAGE_BYTES
from kinocut_sound.mix._errors import MixError
from kinocut_sound.public import mix_job
from tests.test_sound_public_mix import mix_project  # noqa: F401

pytestmark = pytest.mark.skipif(os.name != "posix", reason="supplied mix requires POSIX descriptors")


class Request:
    def model_dump_json(self):
        return "{}"

    def canonical_id(self):
        return "sha256:" + "a" * 64


def worker_script(stderr_bytes):
    status = json.dumps({"ok": True, "request_hash": Request().canonical_id()})
    return f"import os; os.write(2, b'x' * {stderr_bytes}); print({status!r})"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_stderr_limit_is_enforced_before_success(monkeypatch, tmp_path, asynchronous):
    script = worker_script(MAX_MIX_WORKER_MESSAGE_BYTES + 1)
    real_popen = subprocess.Popen
    real_spawn = asyncio.create_subprocess_exec

    def spawn_sync(args, **kwargs):
        return real_popen([sys.executable, "-c", script], **kwargs)

    async def spawn_async(*args, **kwargs):
        return await real_spawn(sys.executable, "-c", script, **kwargs)

    with (tmp_path / "stage").open("wb+") as stage:
        if asynchronous:
            monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn_async)
        else:
            monkeypatch.setattr(subprocess, "Popen", spawn_sync)
        with pytest.raises(MixError) as error:
            if asynchronous:
                asyncio.run(mix_job._run_worker_async(Request(), stage.fileno(), stage.fileno()))
            else:
                mix_job._run_worker(Request(), stage.fileno(), stage.fileno())
        assert error.value.code == "mix_worker_failed"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_oversized_encoded_request_never_spawns(monkeypatch, asynchronous):
    from kinocut_sound.limits import MAX_MIX_REQUEST_BYTES

    class Oversized(Request):
        def model_dump_json(self):
            return "x" * (MAX_MIX_REQUEST_BYTES + 1)

    def forbidden(*args, **kwargs):
        raise AssertionError("oversized request spawned a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    with pytest.raises(MixError) as error:
        if asynchronous:
            asyncio.run(mix_job._run_worker_async(Oversized(), -1, -1))
        else:
            mix_job._run_worker(Oversized(), -1, -1)
    assert error.value.code == "mix_input_invalid"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("pipe", [1, 2])
def test_public_pipe_overflow_leaves_no_output(mix_project, monkeypatch, asynchronous, pipe):  # noqa: F811
    root, request = mix_project
    script = f"import os\nwhile True: os.write({pipe}, b'x'*16384)"
    monkeypatch.setattr(mix_job, "_worker_args", lambda *args: [sys.executable, "-c", script])
    with pytest.raises(MixError) as error:
        if asynchronous:
            asyncio.run(mix_job.render_mix_request_async(request, str(root)))
        else:
            mix_job.render_mix_request(request, str(root))
    assert error.value.code == "mix_worker_failed"
    assert not (root / request["output_path"]).exists()
    assert not list(root.glob(".kinocut-mix-*"))
