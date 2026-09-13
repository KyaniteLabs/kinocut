"""V4 orchestration keeps converters direct and private cleanup before commit."""

import asyncio
import time
import zipfile

from kinocut_sound.defaults import DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.public.mix_conversion_prepare import _prepared_assets, _prepared_assets_async
from kinocut_sound.public.mix_conversion_proof import (
    _verified_conversion_rows,
    _proof_parts,
    _verify_conversion_receipt,
)
from kinocut_sound.public.mix_files import open_root, open_parent, staged_output, publish
from kinocut_sound.public.mix_job import _worker_args, _encoded_request, _worker_status, _verify_stage, _result
from kinocut_sound.public.mix_process import remaining, run_worker_sync
from kinocut_sound.public.mix_process_async import run_worker_async


def _prepared_worker_args(prepared, stage_fd):
    args = [*_worker_args(prepared.root_fd, stage_fd), str(prepared.manifest_fd)]
    return args, (prepared.root_fd, stage_fd, prepared.manifest_fd)


def _verified_result(stage_fd, request, prepared, rows):
    layers, automated, windows = _proof_parts(request, rows)
    receipt, archive_hash = _verify_stage(stage_fd, request, layers, automated)
    _verify_conversion_receipt(receipt, request, prepared, windows)
    return _result(request, receipt, archive_hash)


def _render_converted_mix(request, project_root):
    deadline = time.monotonic() + DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS
    try:
        with (
            open_root(project_root) as original_root,
            open_parent(original_root, request.output_path) as (parent_fd, name),
            staged_output(parent_fd) as (stage_fd, stage_name),
        ):
            with _prepared_assets(request, original_root, deadline) as prepared:
                args, descriptors = _prepared_worker_args(prepared, stage_fd)
                code, status = run_worker_sync(args, _encoded_request(request), descriptors, remaining(deadline))
                _worker_status(request, code, status)
                rows = tuple(_verified_conversion_rows(prepared, request, original_root, deadline))
                result = _verified_result(stage_fd, request, prepared, rows)
            remaining(deadline)
            publish(parent_fd, stage_name, name)
        return result
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        raise mix_error("converted mix could not be verified or published", "mix_publish_failed") from exc


async def _render_converted_mix_async(request, project_root):
    deadline = time.monotonic() + DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS
    try:
        with (
            open_root(project_root) as original_root,
            open_parent(original_root, request.output_path) as (parent_fd, name),
            staged_output(parent_fd) as (stage_fd, stage_name),
        ):
            async with _prepared_assets_async(request, original_root, deadline) as prepared:
                args, descriptors = _prepared_worker_args(prepared, stage_fd)
                code, status = await run_worker_async(args, _encoded_request(request), descriptors, remaining(deadline))
                _worker_status(request, code, status)
                rows = []
                for row in _verified_conversion_rows(prepared, request, original_root, deadline):
                    rows.append(row)
                    await asyncio.sleep(0)
                result = _verified_result(stage_fd, request, prepared, rows)
            await asyncio.sleep(0)
            remaining(deadline)
            publish(parent_fd, stage_name, name)
        return result
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        raise mix_error("converted mix could not be verified or published", "mix_publish_failed") from exc
