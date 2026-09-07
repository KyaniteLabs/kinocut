"""Sidecar-wide direct-child cleanup that survives repeated caller cancellation."""

import asyncio
from contextlib import suppress


async def finish_despite_cancellation(task):
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    return task.result(), cancelled


async def reap_process(process):
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()
    _, cancelled = await finish_despite_cancellation(asyncio.create_task(process.wait()))
    return cancelled
