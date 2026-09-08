"""Async direct-child ownership through spawn and repeated cancellation."""

import asyncio
from contextlib import suppress
import time

from kinocut_sound._process_ownership import finish_despite_cancellation
from kinocut_sound.limits import (
    MAX_MIX_WORKER_MESSAGE_BYTES,
    MAX_MIX_WORKER_DIAGNOSTIC_BYTES,
    MIX_WORKER_IO_CHUNK_BYTES,
)
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.public.mix_process import append_bounded, remaining


async def _read(stream, limit):
    output = bytearray()
    while chunk := await stream.read(MIX_WORKER_IO_CHUNK_BYTES):
        append_bounded(output, chunk, limit)
    return bytes(output)


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
        with suppress(ProcessLookupError):
            process.kill()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    process.stdin.close()
    await asyncio.gather(_discard(process.stdout), _discard(process.stderr), process.wait())
    with suppress(BrokenPipeError, ConnectionResetError):
        await process.stdin.wait_closed()


async def _recover_spawn(spawn):
    (process, _error), spawn_cancelled = await finish_despite_cancellation(spawn)
    if process is None:
        return spawn_cancelled
    _, cleanup_cancelled = await finish_despite_cancellation(asyncio.create_task(_cleanup(process)))
    return spawn_cancelled or cleanup_cancelled


async def _spawn(args, pass_fds):
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            pass_fds=pass_fds,
            close_fds=True,
        )
        return process, None
    except OSError as exc:
        # Return the outcome so repeated cancellation is not lost to task.result().
        return None, exc


async def run_worker_async(args, encoded, pass_fds, timeout):
    deadline = time.monotonic() + timeout
    spawn = asyncio.create_task(_spawn(args, pass_fds))
    try:
        process, error = await asyncio.wait_for(asyncio.shield(spawn), max(0, deadline - time.monotonic()))
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
        asyncio.create_task(_read(process.stdout, MAX_MIX_WORKER_MESSAGE_BYTES)),
        asyncio.create_task(_read(process.stderr, MAX_MIX_WORKER_DIAGNOSTIC_BYTES)),
        asyncio.create_task(_write(process.stdin, encoded)),
        asyncio.create_task(process.wait()),
    ]
    try:
        result = await asyncio.wait_for(asyncio.gather(*tasks), remaining(deadline))
        return process.returncode, result[0]
    except TimeoutError as exc:
        raise mix_error("mix worker exceeded its deadline", "mix_timeout") from exc
    except OSError as exc:
        raise mix_error("mix worker pipe failed", "mix_worker_failed") from exc
    finally:
        _, cancelled = await finish_despite_cancellation(asyncio.create_task(_cleanup(process, tasks)))
        if cancelled:
            raise asyncio.CancelledError
