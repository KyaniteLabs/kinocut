"""Bounded direct-child ownership for optional local stock speech."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import shutil
import subprocess
import tempfile
import time

from kinocut_sound.defaults import DEFAULT_DUB_UTTERANCE_TIMEOUT_SECONDS
from kinocut_sound.limits import MAX_MIX_WORKER_MESSAGE_BYTES
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.validation import ESPEAK_VERSION_RE


def resolve_engine() -> str:
    executable = shutil.which("espeak-ng")
    if executable is None:
        raise mix_error("local caption speech requires espeak-ng on PATH", "dub_backend_unavailable")
    return executable


def remaining(deadline: float) -> float:
    duration = deadline - time.monotonic()
    if duration <= 0:
        raise mix_error("local caption speech exceeded its overall deadline", "dub_timeout")
    return min(duration, DEFAULT_DUB_UTTERANCE_TIMEOUT_SECONDS)


def _validate_result(returncode, stdout, stderr):
    if returncode != 0:
        raise mix_error("local speech engine failed", "dub_backend_failed")
    if len(stdout) + len(stderr) > MAX_MIX_WORKER_MESSAGE_BYTES:
        raise mix_error("local speech engine diagnostics exceeded limit", "dub_backend_failed")
    return stdout


def run_sync(args: list[str], text: bytes, deadline: float) -> bytes:
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            result = subprocess.run(  # noqa: S603 - fixed local engine argv, untrusted text only on stdin
                args,
                input=text,
                stdout=stdout,
                stderr=stderr,
                timeout=remaining(deadline),
                check=False,
            )
            remaining(deadline)
            return _read_diagnostics(result.returncode, stdout, stderr)
    except subprocess.TimeoutExpired as exc:
        raise mix_error("local speech engine exceeded its deadline", "dub_timeout") from exc
    except OSError as exc:
        raise mix_error("local speech engine cannot execute", "dub_backend_unavailable") from exc


def _read_diagnostics(returncode, stdout, stderr):
    stdout.seek(0)
    stderr.seek(0)
    output = stdout.read(MAX_MIX_WORKER_MESSAGE_BYTES + 1)
    error = stderr.read(MAX_MIX_WORKER_MESSAGE_BYTES + 1)
    return _validate_result(returncode, output, error)


async def _finish_despite_cancellation(task):
    """Wait for owned cleanup even if callers repeatedly cancel the waiter."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    return task.result(), cancelled


async def _reap(process):
    if process.returncode is None:
        # The child may exit between the returncode check and signal.
        with suppress(ProcessLookupError):
            process.kill()
    _, cancelled = await _finish_despite_cancellation(asyncio.create_task(process.wait()))
    return cancelled


async def run_async(args: list[str], text: bytes, deadline: float) -> bytes:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        return await _run_async_files(args, text, deadline, stdout, stderr)


async def _run_async_files(args, text, deadline, stdout, stderr):
    remaining(deadline)
    spawn = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
        )
    )
    try:
        process = await asyncio.shield(spawn)
    except asyncio.CancelledError:
        process, _ = await _finish_despite_cancellation(spawn)
        await _reap(process)
        raise
    except OSError as exc:
        raise mix_error("local speech engine cannot execute", "dub_backend_unavailable") from exc
    try:
        await asyncio.wait_for(process.communicate(text), timeout=remaining(deadline))
        remaining(deadline)
        return _read_diagnostics(process.returncode, stdout, stderr)
    except TimeoutError as exc:
        raise mix_error("local speech engine exceeded its deadline", "dub_timeout") from exc
    finally:
        if await _reap(process):
            raise asyncio.CancelledError


def engine_version(stdout: bytes) -> str:
    match = ESPEAK_VERSION_RE.search(stdout.decode("utf-8", errors="replace"))
    if match is None:
        raise mix_error("local speech engine returned unrecognized identity", "dub_backend_failed")
    return match.group(1)
