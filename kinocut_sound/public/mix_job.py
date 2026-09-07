"""Supplied-media mix execution with a bounded worker and exclusive commit."""

from __future__ import annotations

import hashlib
import asyncio
import json
import os
import subprocess
import sys
import zipfile

from kinocut_sound.defaults import DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS
from kinocut_sound.limits import MAX_MIX_REQUEST_BYTES, MAX_MIX_WORKER_MESSAGE_BYTES
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.public.mix_files import open_parent, open_root, publish, staged_output
from kinocut_sound.public.mix_request import load_mix_request


def _run_worker(request, root_fd, stage_fd):
    encoded = request.model_dump_json().encode()
    if len(encoded) > MAX_MIX_REQUEST_BYTES:
        raise mix_error("encoded mix request exceeds limit", MIX_INPUT_INVALID)
    try:
        completed = subprocess.run(  # noqa: S603 - fixed Python module, descriptor integers; JSON only on stdin
            [sys.executable, "-m", "kinocut_sound.public.mix_worker", str(root_fd), str(stage_fd)],
            input=encoded,
            capture_output=True,
            pass_fds=(root_fd, stage_fd),
            timeout=DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise mix_error("mix worker exceeded its deadline", "mix_timeout") from exc
    return _worker_status(request, completed.returncode, completed.stdout)


def _worker_status(request, returncode, stdout):
    if len(stdout) > MAX_MIX_WORKER_MESSAGE_BYTES:
        raise mix_error("mix worker response exceeds limit", "mix_worker_failed")
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeError) as exc:
        raise mix_error("mix worker returned invalid status", "mix_worker_failed") from exc
    if not isinstance(result, dict) or returncode != 0 or result.get("ok") is not True:
        code = result.get("code", "mix_worker_failed") if isinstance(result, dict) else "mix_worker_failed"
        raise mix_error("mix worker rejected the request", code)
    if result.get("request_hash") != request.canonical_id():
        raise mix_error("mix worker returned mismatched request", "mix_worker_failed")
    return result


def _verify_stage(stage_fd, request):
    os.lseek(stage_fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(stage_fd), "rb") as source:
        with zipfile.ZipFile(source) as archive:
            info = archive.getinfo("receipt.json")
            if info.file_size > MAX_MIX_REQUEST_BYTES * 2:
                raise mix_error("mix receipt exceeds limit", "mix_worker_failed")
            receipt = json.loads(archive.read(info))
            if receipt["request_hash"] != request.canonical_id() or receipt["plan_hash"] != request.plan.canonical_id():
                raise mix_error("mix receipt identity mismatch", "mix_worker_failed")
            if set(archive.namelist()) != {"receipt.json", *receipt["media"]}:
                raise mix_error("mix bundle members mismatch", "mix_worker_failed")
            for name, expected in receipt["media"].items():
                digest = hashlib.sha256()
                size = 0
                with archive.open(name) as member:
                    while data := member.read(MAX_MIX_WORKER_MESSAGE_BYTES):
                        digest.update(data)
                        size += len(data)
                if expected != {"bytes": size, "sha256": "sha256:" + digest.hexdigest()}:
                    raise mix_error("mix output hash mismatch", "mix_worker_failed")
        source.seek(0)
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return receipt, "sha256:" + digest


def render_mix_request(payload, project_root):
    request = load_mix_request(payload)
    if not isinstance(project_root, str) or not project_root:
        raise mix_error("supplied-media mix requires an explicit project root", MIX_INPUT_INVALID)
    try:
        with (
            open_root(project_root) as root_fd,
            open_parent(root_fd, request.output_path) as (parent_fd, name),
            staged_output(parent_fd) as (stage_fd, stage_name),
        ):
            _run_worker(request, root_fd, stage_fd)
            receipt, archive_hash = _verify_stage(stage_fd, request)
            publish(parent_fd, stage_name, name)
        return _result(request, receipt, archive_hash)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise mix_error("mix output could not be verified or published", "mix_publish_failed") from exc


def _result(request, receipt, archive_hash):
    return {
        "ok": True,
        "demo": False,
        "output_path": request.output_path,
        "output_sha256": archive_hash,
        "request_hash": request.canonical_id(),
        "plan_hash": request.plan.canonical_id(),
        "declared_duration_seconds": receipt["declared_duration_seconds"],
        "measured_duration_seconds": receipt["measured_duration_seconds"],
        "within_tolerance": receipt["within_tolerance"],
        "sample_count": receipt["sample_count"],
        "mastering_status": "not_applied",
        "human_review_required": True,
    }


async def _run_worker_async(request, root_fd, stage_fd):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "kinocut_sound.public.mix_worker",
        str(root_fd),
        str(stage_fd),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        pass_fds=(root_fd, stage_fd),
    )
    try:
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(request.model_dump_json().encode()), DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS
        )
        return _worker_status(request, process.returncode, stdout)
    except TimeoutError as exc:
        raise mix_error("mix worker exceeded its deadline", "mix_timeout") from exc
    finally:
        if process.returncode is None:
            process.kill()
        await asyncio.shield(process.wait())


async def render_mix_request_async(payload, project_root):
    """MCP cancellation kills/reaps its worker before staging is cleaned."""
    request = load_mix_request(payload)
    if not isinstance(project_root, str) or not project_root:
        raise mix_error("supplied-media mix requires an explicit project root", MIX_INPUT_INVALID)
    try:
        with (
            open_root(project_root) as root_fd,
            open_parent(root_fd, request.output_path) as (parent_fd, name),
            staged_output(parent_fd) as (stage_fd, stage_name),
        ):
            await _run_worker_async(request, root_fd, stage_fd)
            # Observe pending cancellation before synchronous verification/commit.
            await asyncio.sleep(0)
            receipt, archive_hash = _verify_stage(stage_fd, request)
            await asyncio.sleep(0)
            publish(parent_fd, stage_name, name)
        return _result(request, receipt, archive_hash)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise mix_error("mix output could not be verified or published", "mix_publish_failed") from exc
