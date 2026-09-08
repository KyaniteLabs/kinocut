"""Real concurrent pipe pressure, EOF order and deadline ownership."""

import asyncio
import os
import subprocess
import sys

import pytest

from kinocut_sound.limits import MAX_MIX_WORKER_MESSAGE_BYTES, MAX_MIX_WORKER_DIAGNOSTIC_BYTES
from kinocut_sound.mix._errors import MixError
from kinocut_sound.public.mix_process import run_worker_sync
from kinocut_sound.public.mix_process_async import run_worker_async

pytestmark = pytest.mark.skipif(os.name != "posix", reason="supplied mix requires POSIX descriptors")


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def run(request):
    def execute(script, encoded=b"{}", timeout=3):
        args = [sys.executable, "-c", script]
        if request.param:
            return asyncio.run(run_worker_async(args, encoded, (), timeout))
        return run_worker_sync(args, encoded, (), timeout)

    return execute


@pytest.fixture
def children(monkeypatch):
    original = subprocess.Popen
    children = []

    def tracked(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(subprocess, "Popen", tracked)
    yield children
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)


def test_both_pipe_caps_are_inclusive(run):
    code, output = run(
        f"import os; os.write(1,b'a'*{MAX_MIX_WORKER_MESSAGE_BYTES}); "
        f"os.write(2,b'b'*{MAX_MIX_WORKER_DIAGNOSTIC_BYTES})"
    )
    assert code == 0 and output == b"a" * MAX_MIX_WORKER_MESSAGE_BYTES


@pytest.mark.parametrize("pipe", [1, 2])
def test_flood_is_stopped_before_deadline(run, children, pipe):
    with pytest.raises(MixError) as error:
        run(f"import os\nwhile True: os.write({pipe}, b'x'*16384)", timeout=3)
    assert error.value.code == "mix_worker_failed"
    assert children and all(child.poll() is not None for child in children)


@pytest.mark.parametrize("closed", [1, 2])
def test_each_eof_is_independent(run, closed):
    other = 3 - closed
    code, output = run(f"import os; os.close({closed}); os.write({other}, b'alive')")
    assert code == 0 and output == (b"alive" if other == 1 else b"")


def test_both_outputs_closed_still_waits_for_child(run, children):
    with pytest.raises(MixError) as error:
        run("import os,time; os.close(1); os.close(2); time.sleep(10)", timeout=0.2)
    assert error.value.code == "mix_timeout"
    assert children and all(child.poll() is not None for child in children)


def test_unread_stdin_obeys_total_deadline(run, children):
    with pytest.raises(MixError) as error:
        run("import time; time.sleep(10)", encoded=b"x" * 1_000_000, timeout=0.2)
    assert error.value.code == "mix_timeout"
    assert children and all(child.poll() is not None for child in children)


def test_early_stdin_close_retains_worker_status(run):
    code, output = run("import os; os.close(0); print('rejected'); raise SystemExit(7)", encoded=b"x" * 1_000_000)
    assert code == 7 and output == b"rejected\n"


def test_large_stdin_and_output_progress_together(run):
    script = "import os,sys; os.write(2,b'd'*32768); data=sys.stdin.buffer.read(); print(len(data))"
    assert run(script, b"x" * 100_000) == (0, b"100000\n")


def test_partial_and_temporarily_blocked_writes(monkeypatch):
    original = os.write
    calls = 0

    def partial(fd, data):
        nonlocal calls
        if isinstance(data, memoryview):
            calls += 1
            if calls == 1:
                raise BlockingIOError
            data = data[:3]
        return original(fd, data)

    monkeypatch.setattr(os, "write", partial)
    args = [sys.executable, "-c", "import sys; print(len(sys.stdin.buffer.read()))"]
    assert run_worker_sync(args, b"x" * 101, (), 3) == (0, b"101\n")
    assert calls > 2


def test_selector_interruption_keeps_deadline(monkeypatch):
    from kinocut_sound.public import mix_process

    original = mix_process.selectors.DefaultSelector

    class Interrupted(original):
        interrupted = False

        def select(self, timeout=None):
            if not self.interrupted:
                self.interrupted = True
                raise InterruptedError
            return super().select(timeout)

    monkeypatch.setattr(mix_process.selectors, "DefaultSelector", Interrupted)
    assert run_worker_sync([sys.executable, "-c", "print('ready')"], b"{}", (), 3) == (0, b"ready\n")


def test_sync_interruption_reaps_only_owned_child(monkeypatch, children):
    from kinocut_sound.public import mix_process

    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    original = mix_process.selectors.DefaultSelector

    class Interrupted(original):
        def select(self, timeout=None):
            raise KeyboardInterrupt

    monkeypatch.setattr(mix_process.selectors, "DefaultSelector", Interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_worker_sync([sys.executable, "-c", "import time; time.sleep(10)"], b"{}", (), 3)
    assert sentinel.poll() is None
    assert len(children) == 2 and children[1].poll() is not None


def test_repeated_sync_interrupt_during_reaping(monkeypatch, children):
    original = subprocess.Popen
    waits = []

    def interrupted(*args, **kwargs):
        process = original(*args, **kwargs)
        real_wait = process.wait

        def wait(*args, **kwargs):
            waits.append(True)
            if len(waits) <= 2:
                raise KeyboardInterrupt
            return real_wait(*args, **kwargs)

        process.wait = wait
        return process

    monkeypatch.setattr(subprocess, "Popen", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_worker_sync([sys.executable, "-c", "pass"], b"{}", (), 3)
    assert len(waits) >= 3 and children[0].poll() is not None
