"""Bounded IPC for the directly owned pure-Python mix worker."""

from contextlib import suppress
import os
import selectors
import subprocess
import threading
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


def _exchange_threaded(process, encoded, deadline, stdout_sink, stdout_limit):
    """Portable bounded pipe exchange for platforms without non-blocking pipe selectors (e.g. Windows)."""
    stdout = BoundedOutput(stdout_limit, stdout_sink)
    stderr = BoundedOutput(MAX_MIX_WORKER_DIAGNOSTIC_BYTES)
    errors: list[BaseException] = []

    def _writer():
        try:
            if encoded:
                for offset in range(0, len(encoded), MIX_WORKER_IO_CHUNK_BYTES):
                    process.stdin.write(memoryview(encoded)[offset : offset + MIX_WORKER_IO_CHUNK_BYTES])
                process.stdin.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with suppress(OSError):
                process.stdin.close()

    def _reader(stream, bounded):
        try:
            while True:
                chunk = stream.read(MIX_WORKER_IO_CHUNK_BYTES)
                if not chunk:
                    break
                bounded.append(chunk)
        except BaseException as exc:
            errors.append(exc)
            with suppress(OSError):
                process.kill()
        finally:
            with suppress(OSError):
                stream.close()

    threads = [
        threading.Thread(target=_writer, daemon=True),
        threading.Thread(target=_reader, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=_reader, args=(process.stderr, stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    process.wait(timeout=remaining(deadline))
    for thread in threads:
        thread.join(timeout=remaining(deadline))
        if thread.is_alive():
            raise mix_error("mix worker exceeded its deadline", "mix_timeout")
    if errors:
        raise errors[0]
    return process.returncode, stdout.value()


def _exchange(process, encoded, deadline, stdout_sink, stdout_limit):
    if os.name != "posix" or not hasattr(os, "set_blocking"):
        return _exchange_threaded(process, encoded, deadline, stdout_sink, stdout_limit)
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
                with suppress(ProcessLookupError, OSError):
                    process.kill()
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    with suppress(OSError):
                        stream.close()
            process.wait()
            break
        except KeyboardInterrupt:
            interrupted = True
    if interrupted:
        raise KeyboardInterrupt


def run_worker_sync(args, encoded, pass_fds, timeout, *, stdout_sink=None, stdout_limit=MAX_MIX_WORKER_MESSAGE_BYTES):
    deadline = time.monotonic() + timeout
    if os.name != "posix" and pass_fds:
        raise mix_error("mix worker descriptor inheritance requires POSIX", "mix_worker_failed")
    popen_kwargs = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "close_fds": True,
    }
    if os.name == "posix":
        popen_kwargs["pass_fds"] = pass_fds
    try:
        # Popen has no timeout argument; selector and wait share the deadline.
        process = subprocess.Popen(  # noqa: S603 - fixed module argv and held descriptors
            args,
            **popen_kwargs,
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
