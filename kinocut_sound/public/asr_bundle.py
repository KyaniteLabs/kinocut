"""Retain actual recognition privately and publish only a verified archive."""

import hashlib
import io
import json
import os
import zipfile

from kinocut_sound.limits import MAX_ASR_OUTPUT_BYTES
from kinocut_sound.public.asr_compare import remaining
from kinocut_sound.public.asr_request import asr_error


def prepare_bundle(job, transcript, segments, comparison, backend):
    receipt = {
        "artifact_kind": "recognized_sound_asr",
        "demo": False,
        "request_hash": job.request.canonical_id(),
        "source_sha256": job.request.source.sha256,
        "reference_sha256": job.request.reference.sha256,
        "backend": backend,
        "verification_status": "recognized_match" if comparison["ok"] else "recognized_mismatch",
        "human_review_required": True,
        "comparison": comparison,
    }
    content = json.dumps({"text": transcript, "segments": segments}, ensure_ascii=False, allow_nan=False).encode()
    receipt["transcript_sha256"] = "sha256:" + hashlib.sha256(content).hexdigest()
    encoded = json.dumps(receipt, sort_keys=True, allow_nan=False).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(zipfile.ZipInfo("transcript.json"), content)
        archive.writestr(zipfile.ZipInfo("receipt.json"), encoded)
    archive_bytes = buffer.getvalue()
    if len(archive_bytes) > MAX_ASR_OUTPUT_BYTES:
        raise asr_error("ASR archive exceeds bound", "asr_over_limit")
    remaining(job.deadline)
    with os.fdopen(os.dup(job.stage_fd), "w+b") as output:
        output.write(archive_bytes)
        output.flush()
        os.fsync(output.fileno())
        output.seek(0)
        retained = output.read(MAX_ASR_OUTPUT_BYTES + 1)
    if retained != archive_bytes:
        raise asr_error("ASR archive bytes changed", "asr_invalid_output")
    with zipfile.ZipFile(io.BytesIO(retained)) as archive:
        if sorted(archive.namelist()) != ["receipt.json", "transcript.json"]:
            raise asr_error("ASR archive members changed", "asr_invalid_output")
        if archive.read("transcript.json") != content or archive.read("receipt.json") != encoded:
            raise asr_error("ASR archive content changed", "asr_invalid_output")
    remaining(job.deadline)
    return {
        **receipt,
        "ok": comparison["ok"],
        "output_path": job.request.output_path,
        "output_sha256": "sha256:" + hashlib.sha256(retained).hexdigest(),
    }
