"""Bound diagnostics while a meter runs; own its direct child until reaped."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
import subprocess
import threading
import time

from kinocut_sound.limits import LOUDNESS_DIAGNOSTIC_CHUNK_BYTES, MAX_LOUDNESS_DIAGNOSTIC_BYTES
from kinocut_sound._process_ownership import finish_despite_cancellation
from kinocut_sound.qa._errors import QA_UNAVAILABLE, QaError, qa_error

logger = logging.getLogger(__name__)


def _append(output, chunk):
    if len(output) + len(chunk) > MAX_LOUDNESS_DIAGNOSTIC_BYTES:
        raise qa_error("meter diagnostics exceeded limit", "qa_meter_over_limit")
    output.extend(chunk)


def _validate_exit(returncode, output):
    if returncode:
        if b"no such filter" in bytes(output).lower():
            raise qa_error("meter requires the ebur128 filter", QA_UNAVAILABLE)
        raise qa_error("meter backend failed", "qa_meter_failed")
    return bytes(output)


def _kill(process):
    if process.poll() is None:
        with suppress(ProcessLookupError):
            process.kill()


def _reader(process, output, errors):
    try:
        while chunk := process.stdout.read(LOUDNESS_DIAGNOSTIC_CHUNK_BYTES):
            _append(output, chunk)
    except Exception as exc:
        logger.warning("meter diagnostic reader stopped (%s)", type(exc).__name__)
        errors.append(exc if isinstance(exc, QaError) else qa_error("meter diagnostic reader failed", QA_UNAVAILABLE))
        _kill(process)


def run_meter_sync(args, timeout):
    # Popen has no timeout keyword; wait below owns the bounded execution.
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed meter argv, no shell
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        raise qa_error("meter backend unavailable", QA_UNAVAILABLE) from exc
    output, errors = bytearray(), []
    reader = threading.Thread(target=_reader, args=(process, output, errors))
    reader_started = False
    try:
        reader.start()
        reader_started = True
        process.wait(timeout=timeout)
        reader.join()
        if errors:
            raise errors[0]
        return _validate_exit(process.returncode, output)
    except subprocess.TimeoutExpired as exc:
        raise qa_error("meter exceeded deadline", "qa_meter_timeout") from exc
    except RuntimeError as exc:
        raise qa_error("meter reader unavailable", QA_UNAVAILABLE) from exc
    finally:
        _kill(process)
        # Repeated interrupts must not abandon the child or reader.
        interrupted = False
        while True:
            try:
                process.wait()
                if reader_started:
                    reader.join()
                break
            except KeyboardInterrupt:
                interrupted = True
                _kill(process)
        process.stdout.close()
        if interrupted:
            raise KeyboardInterrupt


async def run_meter_async(args, timeout):
    deadline = time.monotonic() + timeout
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    )
    try:
        process = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        process, _ = await finish_despite_cancellation(spawn)
        await _cleanup_async(process)
        raise
    except OSError as exc:
        raise qa_error("meter backend unavailable", QA_UNAVAILABLE) from exc
    try:
        output = await asyncio.wait_for(_read_async(process), timeout=max(0, deadline - time.monotonic()))
        return _validate_exit(process.returncode, output)
    except TimeoutError as exc:
        raise qa_error("meter exceeded deadline", "qa_meter_timeout") from exc
    finally:
        if await _cleanup_async(process):
            raise asyncio.CancelledError


async def _read_async(process):
    output = bytearray()
    while chunk := await process.stdout.read(LOUDNESS_DIAGNOSTIC_CHUNK_BYTES):
        _append(output, chunk)
    await process.wait()
    return output


async def _cleanup_async(process):
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()

    async def drain_and_wait():
        # A paused PIPE transport can keep wait() pending even after SIGKILL.
        # Drain without retaining diagnostics before joining the dead child.
        while await process.stdout.read(LOUDNESS_DIAGNOSTIC_CHUNK_BYTES):
            pass
        await process.wait()

    _, cancelled = await finish_despite_cancellation(asyncio.create_task(drain_and_wait()))
    return cancelled
