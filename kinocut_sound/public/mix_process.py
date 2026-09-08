"""Bounded IPC for the directly owned pure-Python mix worker."""

from contextlib import suppress
import os
import selectors
import subprocess
import time

from kinocut_sound.limits import (
    MAX_MIX_WORKER_MESSAGE_BYTES,
    MAX_MIX_WORKER_DIAGNOSTIC_BYTES,
    MIX_WORKER_IO_CHUNK_BYTES,
)
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.public.mix_process_output import BoundedOutput


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise mix_error("mix worker exceeded its deadline", "mix_timeout")
    return seconds


def _close_stream(selector, stream):
    selector.unregister(stream)
    stream.close()


def _write_ready(selector, stream, encoded, offset):
    try:
        offset += os.write(stream.fileno(), memoryview(encoded)[offset : offset + MIX_WORKER_IO_CHUNK_BYTES])
    except BlockingIOError:
        return offset
    except BrokenPipeError:
        _close_stream(selector, stream)
        return offset
    if offset == len(encoded):
        _close_stream(selector, stream)
    return offset


def _exchange(process, encoded, deadline, stdout_sink, stdout_limit):
    stdout = BoundedOutput(stdout_limit, stdout_sink)
    stderr = BoundedOutput(MAX_MIX_WORKER_DIAGNOSTIC_BYTES)
    with selectors.DefaultSelector() as selector:
        for stream, events in (
            (process.stdin, selectors.EVENT_WRITE),
            (process.stdout, selectors.EVENT_READ),
            (process.stderr, selectors.EVENT_READ),
        ):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, events)
        if not encoded:
            _close_stream(selector, process.stdin)
        offset = 0
        while selector.get_map():
            try:
                events = selector.select(remaining(deadline))
            except InterruptedError:
                continue
            for key, _events in events:
                stream = key.fileobj
                if stream is process.stdin:
                    offset = _write_ready(selector, stream, encoded, offset)
                    continue
                try:
                    chunk = os.read(stream.fileno(), MIX_WORKER_IO_CHUNK_BYTES)
                except BlockingIOError:
                    continue
                if not chunk:
                    _close_stream(selector, stream)
                elif stream is process.stdout:
                    stdout.append(chunk)
                else:
                    stderr.append(chunk)
        process.wait(timeout=remaining(deadline))
    return process.returncode, stdout.value()


def _cleanup(process):
    interrupted = False
    while True:
        try:
            if process.poll() is None:
                with suppress(ProcessLookupError):
                    process.kill()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            process.wait()
            break
        except KeyboardInterrupt:
            interrupted = True
    if interrupted:
        raise KeyboardInterrupt


def run_worker_sync(args, encoded, pass_fds, timeout, *, stdout_sink=None, stdout_limit=MAX_MIX_WORKER_MESSAGE_BYTES):
    deadline = time.monotonic() + timeout
    try:
        # Popen has no timeout argument; selector and wait share the deadline.
        process = subprocess.Popen(  # noqa: S603 - fixed module argv and held descriptors
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=pass_fds,
            close_fds=True,
        )
    except OSError as exc:
        raise mix_error("mix worker could not start", "mix_worker_failed") from exc
    try:
        return _exchange(process, encoded, deadline, stdout_sink, stdout_limit)
    except subprocess.TimeoutExpired as exc:
        raise mix_error("mix worker exceeded its deadline", "mix_timeout") from exc
    except OSError as exc:
        raise mix_error("mix worker pipe failed", "mix_worker_failed") from exc
    finally:
        _cleanup(process)
