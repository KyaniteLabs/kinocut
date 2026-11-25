"""Async direct-child ownership through spawn and repeated cancellation."""

import asyncio
from contextlib import suppress
import os
import time

from kinocut_sound._process_ownership import finish_despite_cancellation
from kinocut_sound.limits import (
    MAX_MIX_WORKER_MESSAGE_BYTES,
    MAX_MIX_WORKER_DIAGNOSTIC_BYTES,
    MIX_WORKER_IO_CHUNK_BYTES,
)
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.public.mix_process import remaining
from kinocut_sound.public.mix_process_output import BoundedOutput


async def _read(stream, limit, sink=None):
    output = BoundedOutput(limit, sink)
    while chunk := await stream.read(MIX_WORKER_IO_CHUNK_BYTES):
        output.append(chunk)
    return output.value()


async def _write(stream, encoded):
    try:
        for offset in range(0, len(encoded), MIX_WORKER_IO_CHUNK_BYTES):
            stream.write(memoryview(encoded)[offset : offset + MIX_WORKER_IO_CHUNK_BYTES])
            await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        stream.close()


async def _discard(stream):
    with suppress(BrokenPipeError, ConnectionResetError):
        while await stream.read(MIX_WORKER_IO_CHUNK_BYTES):
            pass


async def _cleanup(process, tasks=()):
    if process.returncode is None:
        with suppress(ProcessLookupError, OSError):
            process.kill()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if process.stdin is not None:
        process.stdin.close()
    await asyncio.gather(
        *([_discard(process.stdout)] if process.stdout is not None else []),
        *([_discard(process.stderr)] if process.stderr is not None else []),
        process.wait(),
    )
    if process.stdin is not None:
        with suppress(BrokenPipeError, ConnectionResetError, OSError):
            await process.stdin.wait_closed()


async def _recover_spawn(spawn):
    (process, _error), spawn_cancelled = await finish_despite_cancellation(spawn)
    if process is None:
        return spawn_cancelled
    _, cleanup_cancelled = await finish_despite_cancellation(asyncio.create_task(_cleanup(process)))
    return spawn_cancelled or cleanup_cancelled


async def _spawn(args, pass_fds):
    if os.name != "posix" and pass_fds:
        return None, OSError("pass_fds is not supported on this platform")
    extra_kwargs = {"pass_fds": pass_fds} if os.name == "posix" else {}
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            close_fds=True,
            **extra_kwargs,
        )
        return process, None
    except OSError as exc:
        # Return the outcome so repeated cancellation is not lost to task.result().
        return None, exc


async def run_worker_async(
    args, encoded, pass_fds, timeout, *, stdout_sink=None, stdout_limit=MAX_MIX_WORKER_MESSAGE_BYTES
):
    deadline = time.monotonic() + timeout
    spawn = asyncio.create_task(_spawn(args, pass_fds))
    try:
        # asyncio.timeout, not wait_for: on Python 3.11 wait_for drops a cancel
        # that lands just as the inner future finishes (#701).
        async with asyncio.timeout(max(0, deadline - time.monotonic())):
            process, error = await asyncio.shield(spawn)
        if error is not None:
            raise error
    except asyncio.CancelledError:
        await _recover_spawn(spawn)
        raise
    except TimeoutError as exc:
        if await _recover_spawn(spawn):
            raise asyncio.CancelledError from exc
        raise mix_error("mix worker exceeded its deadline", "mix_timeout") from exc
    except OSError as exc:
        raise mix_error("mix worker could not start", "mix_worker_failed") from exc
    tasks = [
        asyncio.create_task(_read(process.stdout, stdout_limit, stdout_sink)),
        asyncio.create_task(_read(process.stderr, MAX_MIX_WORKER_DIAGNOSTIC_BYTES)),
        asyncio.create_task(_write(process.stdin, encoded)),
        asyncio.create_task(process.wait()),
    ]
    try:
        async with asyncio.timeout(remaining(deadline)):
            result = await asyncio.gather(*tasks)
        return process.returncode, result[0]
    except TimeoutError as exc:
        raise mix_error("mix worker exceeded its deadline", "mix_timeout") from exc
    except OSError as exc:
        raise mix_error("mix worker pipe failed", "mix_worker_failed") from exc
    finally:
        _, cancelled = await finish_despite_cancellation(asyncio.create_task(_cleanup(process, tasks)))
        if cancelled:
            raise asyncio.CancelledError
