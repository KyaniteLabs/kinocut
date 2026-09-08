"""Retain measured final bytes and verify the archive before publication."""

from dataclasses import asdict
import hashlib
import json
import os
import zipfile

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.limits import MAX_MIX_WORKER_MESSAGE_BYTES
from kinocut_sound.public.master_render import remaining
from kinocut_sound.public.master_request import internal_peak, master_error


def _receipt(job, data, report, version, mode):
    policy = job.request.delivery
    receipt = {
        "artifact_kind": "measured_sound_master",
        "demo": False,
        "request_hash": job.request.canonical_id(),
        "source_sha256": job.request.source.sha256,
        "policy_hash": canonical_digest(policy.model_dump(mode="json")),
        "policy_scope": "numeric_loudness_and_peak_only",
        "backend": {"id": "ffmpeg", "version": version},
        "normalization_type": mode,
        "internal_peak_target_dbtp": internal_peak(policy),
        "effective_peak_ceiling_dbtp": min(policy.loudness.true_peak_dbtp, policy.true_peak_ceiling_dbtp),
        "measurement": asdict(report),
        "input_sample_count": job.input_count,
        "input_sample_rate_hz": job.input_rate,
        "sample_count": job.output_count,
        "sample_rate_hz": job.output_rate,
        "timing_proof": "frame_count_only",
        "mastering_status": "measured_compliant",
        "human_review_required": True,
        "media": {"master.wav": {"bytes": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}},
    }
    receipt.update(_stereo_fields(job))
    return receipt


def _stereo_fields(job):
    if job.channel_count == 1:
        return {}
    return {
        "schema_version": 2,
        "channel_count": job.channel_count,
        "input_frame_count": job.input_count,
        "frame_count": job.output_count,
        "input_interleaved_sample_count": job.input_count * job.channel_count,
        "interleaved_sample_count": job.output_count * job.channel_count,
    }


def _verify(destination, receipt_bytes, receipt, deadline):
    destination.seek(0)
    with zipfile.ZipFile(destination) as archive:
        if sorted(archive.namelist()) != ["master.wav", "receipt.json"]:
            raise master_error("master bundle member mismatch", "master_bundle_invalid")
        info = archive.getinfo("receipt.json")
        if info.file_size != len(receipt_bytes) or archive.read(info) != receipt_bytes:
            raise master_error("master bundle receipt mismatch", "master_bundle_invalid")
        media = receipt["media"]["master.wav"]
        info = archive.getinfo("master.wav")
        if info.file_size != media["bytes"] or info.compress_type != zipfile.ZIP_STORED:
            raise master_error("master bundle media size mismatch", "master_bundle_invalid")
        digest, size = hashlib.sha256(), 0
        with archive.open(info) as source:
            while chunk := source.read(MAX_MIX_WORKER_MESSAGE_BYTES):
                remaining(deadline)
                digest.update(chunk)
                size += len(chunk)
                if size > media["bytes"]:
                    raise master_error("master bundle media exceeds limit", "master_bundle_invalid")
        if size != media["bytes"] or "sha256:" + digest.hexdigest() != media["sha256"]:
            raise master_error("master bundle media hash mismatch", "master_bundle_invalid")
    destination.seek(0)
    digest = hashlib.sha256()
    while chunk := destination.read(MAX_MIX_WORKER_MESSAGE_BYTES):
        remaining(deadline)
        digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def prepare_bundle(job, data, report, version, mode):
    remaining(job.deadline)
    receipt = _receipt(job, data, report, version, mode)
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    try:
        with os.fdopen(os.dup(job.stage_fd), "w+b") as destination:
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr(zipfile.ZipInfo("master.wav"), data)
                remaining(job.deadline)
                archive.writestr(zipfile.ZipInfo("receipt.json"), encoded)
            destination.flush()
            os.fsync(destination.fileno())
            archive_hash = _verify(destination, encoded, receipt, job.deadline)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise master_error("master bundle could not be verified", "master_bundle_invalid") from exc
    remaining(job.deadline)
    return {
        "ok": True,
        "demo": False,
        "output_path": job.request.output_path,
        "output_sha256": archive_hash,
        **_stereo_fields(job),
        **{
            key: receipt[key]
            for key in (
                "request_hash",
                "source_sha256",
                "policy_hash",
                "backend",
                "normalization_type",
                "measurement",
                "sample_count",
                "sample_rate_hz",
                "mastering_status",
                "human_review_required",
            )
        },
    }
