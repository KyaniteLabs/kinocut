"""Raw backend output is bounded before writing an owned sink."""

import asyncio
import os
import sys
import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public.mix_process import run_worker_sync
from kinocut_sound.public.mix_process_async import run_worker_async

pytestmark = pytest.mark.skipif(os.name != "posix", reason="supplied mix requires POSIX descriptors")


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("overflow", [False, True])
def test_sink_does_not_collect_raw_stdout(tmp_path, asynchronous, overflow):
    limit = 100_000
    args = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(b'x'*{limit + overflow})"]
    with (tmp_path / "raw").open("wb+") as sink:

        def call():
            kwargs = {"stdout_sink": sink, "stdout_limit": limit}
            if asynchronous:
                return asyncio.run(run_worker_async(args, b"", (), 3, **kwargs))
            return run_worker_sync(args, b"", (), 3, **kwargs)

        if overflow:
            with pytest.raises(MixError):
                call()
            assert sink.tell() <= limit
        else:
            assert call() == (0, b"")
            sink.seek(0)
            assert sink.read() == b"x" * limit
