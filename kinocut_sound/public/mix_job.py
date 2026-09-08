"""Supplied-media mix execution with a bounded worker and exclusive commit."""

from __future__ import annotations

import hashlib
import asyncio
import json
import os
import sys
import zipfile

from kinocut_sound.defaults import DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS
from kinocut_sound._canonical import canonical_digest
from kinocut_sound.limits import MAX_MIX_REQUEST_BYTES, MAX_MIX_WORKER_MESSAGE_BYTES, MAX_MIX_RECEIPT_BYTES
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.public.mix_files import open_parent, open_root, publish, staged_output
from kinocut_sound.public.mix_request import load_mix_request


def _encoded_request(request):
    encoded = request.model_dump_json().encode()
    if len(encoded) > MAX_MIX_REQUEST_BYTES:
        raise mix_error("encoded mix request exceeds limit", MIX_INPUT_INVALID)
    return encoded


def _worker_args(root_fd, stage_fd):
    return [sys.executable, "-m", "kinocut_sound.public.mix_worker", str(root_fd), str(stage_fd)]


def _run_worker(request, root_fd, stage_fd):
    from kinocut_sound.public.mix_process import run_worker_sync

    encoded = _encoded_request(request)
    code, stdout = run_worker_sync(
        _worker_args(root_fd, stage_fd), encoded, (root_fd, stage_fd), DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS
    )
    return _worker_status(request, code, stdout)


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


def _verify_stage(stage_fd, request, layer_shapes=(), automation_windows=()):
    os.lseek(stage_fd, 0, os.SEEK_SET)
    with os.fdopen(os.dup(stage_fd), "rb") as source:
        with zipfile.ZipFile(source) as archive:
            info = archive.getinfo("receipt.json")
            if info.file_size > MAX_MIX_RECEIPT_BYTES:
                raise mix_error("mix receipt exceeds limit", "mix_worker_failed")
            receipt = json.loads(archive.read(info))
            if receipt["request_hash"] != request.canonical_id() or receipt["plan_hash"] != request.plan.canonical_id():
                raise mix_error("mix receipt identity mismatch", "mix_worker_failed")
            if request.schema_version >= 2:
                from kinocut_sound.public.mix_routing_receipt import verify_routing_receipt

                verify_routing_receipt(receipt, request)
            if request.plan.routing.envelopes:
                from kinocut_sound.public.mix_automation_receipt import verify_automation_windows

                verify_automation_windows(receipt, request, automation_windows)
            if request.schema_version >= 3:
                from kinocut_sound.public.mix_layer_receipt import verify_layer_receipt

                verify_layer_receipt(receipt, request, layer_shapes)
            if request.plan.routing.sends or request.plan.routing.sidechains:
                from kinocut_sound.public.mix_send_request import check_routed_feature_work
                from kinocut_sound.public.mix_request_v2 import compile_routing

                check_routed_feature_work(request, compile_routing(request), automation_windows, layer_shapes)
            if request.plan.routing.sidechains:
                from kinocut_sound.public.mix_sidechain_request import verify_sidechain_measurements

                verify_sidechain_measurements(request, receipt.get("bus_sidechain_measurements"))
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
    if request.schema_version == 4:
        from kinocut_sound.public.mix_conversion_job import _render_converted_mix

        return _render_converted_mix(request, project_root)
    try:
        with (
            open_root(project_root) as root_fd,
            open_parent(root_fd, request.output_path) as (parent_fd, name),
            staged_output(parent_fd) as (stage_fd, stage_name),
        ):
            _run_worker(request, root_fd, stage_fd)
            shapes = ()
            if request.schema_version >= 3:
                from kinocut_sound.public.mix_layer_receipt import verified_layer_shapes

                shapes = tuple(verified_layer_shapes(request, root_fd))
            windows = ()
            if request.plan.routing.envelopes:
                from kinocut_sound.public.mix_automation_receipt import verified_automation_windows

                windows = tuple(verified_automation_windows(request, root_fd))
            receipt, archive_hash = _verify_stage(stage_fd, request, shapes, windows)
            result = _result(request, receipt, archive_hash)
            publish(parent_fd, stage_name, name)
        return result
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        raise mix_error("mix output could not be verified or published", "mix_publish_failed") from exc


def _result(request, receipt, archive_hash):
    result = {
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
    if request.plan.format.channel_count > 1 or request.schema_version >= 2:
        result.update(
            {
                key: receipt[key]
                for key in ("schema_version", "channel_count", "frame_count", "interleaved_sample_count")
            }
        )
    if request.schema_version >= 2:
        result["request_schema_version"] = receipt["request_schema_version"]
        result["routing_algorithm"] = receipt["routing"]["algorithm"]
        result["routing_sha256"] = canonical_digest(receipt["routing"])
        result["routed_cue_count"] = len(receipt["routing"]["cue_tracks"])
        if request.plan.routing.envelopes:
            automation = receipt["routing"]["automation"]
            result["automation_sha256"] = canonical_digest(automation)
            result["automation_envelope_count"] = len(automation["envelopes"])
            result["automation_point_count"] = sum(len(item["points"]) for item in automation["envelopes"])
        if request.plan.routing.sends:
            sends = receipt["routing"]["sends"]
            result["send_count"] = len(sends["sends"])
            result["sends_sha256"] = canonical_digest(sends)
        if request.plan.routing.sidechains:
            result["sidechain_count"] = len(request.plan.routing.sidechains)
            result["sidechains_sha256"] = canonical_digest(receipt["routing"]["sidechains"])
            result["sidechain_measurements_sha256"] = canonical_digest(
                {"measurements": receipt["bus_sidechain_measurements"]}
            )
    if request.schema_version >= 3:
        result["layer_algorithm"] = receipt["layers"]["algorithm"]
        result["layers_sha256"] = canonical_digest(receipt["layers"])
        result["layer_count"] = len(receipt["layers"]["entries"])
        if request.layer_ducking is not None:
            result["layer_ducking_sha256"] = canonical_digest(receipt["layers"]["ducking"])
    if request.schema_version == 4:
        projection = receipt["source_resampling"]
        result["resampling_profile"] = request.source_resampling.profile.value
        result["converted_source_count"] = sum(entry["mode"] == "resample" for entry in projection["entries"])
        result["resampling_sha256"] = canonical_digest(projection)
    return result


async def _run_worker_async(request, root_fd, stage_fd):
    from kinocut_sound.public.mix_process_async import run_worker_async

    encoded = _encoded_request(request)
    code, stdout = await run_worker_async(
        _worker_args(root_fd, stage_fd), encoded, (root_fd, stage_fd), DEFAULT_PUBLIC_MIX_TIMEOUT_SECONDS
    )
    return _worker_status(request, code, stdout)


async def render_mix_request_async(payload, project_root):
    """MCP cancellation kills/reaps its worker before staging is cleaned."""
    request = load_mix_request(payload)
    if not isinstance(project_root, str) or not project_root:
        raise mix_error("supplied-media mix requires an explicit project root", MIX_INPUT_INVALID)
    if request.schema_version == 4:
        from kinocut_sound.public.mix_conversion_job import _render_converted_mix_async

        return await _render_converted_mix_async(request, project_root)
    try:
        with (
            open_root(project_root) as root_fd,
            open_parent(root_fd, request.output_path) as (parent_fd, name),
            staged_output(parent_fd) as (stage_fd, stage_name),
        ):
            await _run_worker_async(request, root_fd, stage_fd)
            # Observe pending cancellation before synchronous verification/commit.
            await asyncio.sleep(0)
            shapes = []
            if request.schema_version >= 3:
                from kinocut_sound.public.mix_layer_receipt import verified_layer_shapes

                for frames in verified_layer_shapes(request, root_fd):
                    shapes.append(frames)
                    await asyncio.sleep(0)
            windows = []
            if request.plan.routing.envelopes:
                from kinocut_sound.public.mix_automation_receipt import verified_automation_windows

                for window in verified_automation_windows(request, root_fd):
                    windows.append(window)
                    await asyncio.sleep(0)
            receipt, archive_hash = _verify_stage(stage_fd, request, shapes, windows)
            result = _result(request, receipt, archive_hash)
            await asyncio.sleep(0)
            publish(parent_fd, stage_name, name)
        return result
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        raise mix_error("mix output could not be verified or published", "mix_publish_failed") from exc
