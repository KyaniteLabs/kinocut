"""Retained local speech media and a directly usable supplied-media mix request."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile

from kinocut_sound.defaults import (
    DEFAULT_DUB_AMPLITUDE,
    DEFAULT_DUB_SAMPLE_RATE_HZ,
    DEFAULT_DUB_WORDS_PER_MINUTE,
)
from kinocut_sound._canonical import canonical_digest
from kinocut_sound.limits import DUB_SPATIAL_METADATA_BYTES
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.public.mix_routing_receipt import bounded_json
from kinocut_sound.delivery import DeliveryPolicy, StemLayout
from kinocut_sound.format import AudioFormat, ChannelLayout, ConversionPolicy, DitherPolicy, SampleFormat, TimeBase
from kinocut_sound.mix._wav import pcm_to_wav
from kinocut_sound.public.dub_process import remaining
from kinocut_sound.public.mix_files import publish
from kinocut_sound.public.mix_request import load_mix_request
from kinocut_sound.routing import Routing
from kinocut_sound.sound_plan import PlanProvenance, SoundPlan
from kinocut_sound.timeline import Cue, CueKind, Timeline


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _encoded(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def mix_manifest(request, dialogue: bytes, sample_count: int) -> dict:
    rate = DEFAULT_DUB_SAMPLE_RATE_HZ
    plan = SoundPlan(
        project_id="dub_" + request.canonical_id().split(":")[1][:20],
        episode_id="caption_speech",
        created_by="tool:local_caption_speech",
        format=AudioFormat(
            channel_layout=ChannelLayout.MONO,
            sample_rate_hz=rate,
            sample_format=SampleFormat.PCM_S16LE,
            time_base=TimeBase.CONTINUOUS,
            conversion=ConversionPolicy(),
            dither=DitherPolicy.NONE,
        ),
        timeline=Timeline(
            cues=(
                Cue(
                    cue_id="dialogue",
                    start_seconds=0,
                    duration_seconds=sample_count / rate,
                    kind=CueKind.LINE,
                    source_ref="dialogue.wav",
                ),
            )
        ),
        routing=Routing(),
        delivery=DeliveryPolicy(stems=StemLayout(stem_ids=("dialogue",))),
        provenance=PlanProvenance(transcript_hashes=(request.source.sha256,)),
    )
    return load_mix_request(
        {
            "plan": plan.model_dump(mode="json"),
            "output_path": "mix.zip",
            "clips": [{"cue_id": "dialogue", "stem_id": "dialogue", "path": "dialogue.wav", "sha256": _sha(dialogue)}],
        }
    ).model_dump(mode="json")


def _spatial_evidence(job):
    if len(job.spatial_cues) != len(job.cues):
        raise mix_error("speech spatial cue evidence is incomplete", "dub_spatial_failed")
    for index, (proof, cue) in enumerate(zip(job.spatial_cues, job.cue_proofs, strict=True), start=1):
        if (
            proof["cue_index"] != index
            or proof["processed_sha256"] != _sha(job.media[cue["path"]])
            or proof["processed_frames"] != cue["speech_samples"]
        ):
            raise mix_error("speech spatial evidence differs from accepted audio", "dub_spatial_failed")
    evidence = {"profile": job.request.spatial_profile, "backend": job.spatial_backend, "cues": job.spatial_cues}
    bounded_json(evidence, DUB_SPATIAL_METADATA_BYTES)
    return evidence


def _prepare_bundle(job) -> dict:
    remaining(job.deadline)
    dialogue = pcm_to_wav(job.pcm, sample_rate_hz=DEFAULT_DUB_SAMPLE_RATE_HZ)
    media = {
        **job.media,
        "dialogue.wav": dialogue,
        "mix-request.json": _encoded(mix_manifest(job.request, dialogue, len(job.pcm))),
    }
    receipt = {
        "artifact_kind": "local_caption_speech_receipt",
        "demo": False,
        "request_hash": job.request.canonical_id(),
        "source_sha256": job.request.source.sha256,
        "backend": {
            "id": "espeak-ng",
            "version": job.version,
            "voice": job.request.selected_voice,
            "words_per_minute": DEFAULT_DUB_WORDS_PER_MINUTE,
            "amplitude": DEFAULT_DUB_AMPLITUDE,
            "deterministic_mode": True,
            "determinism_scope": "same_installation",
        },
        "target_lang": job.request.target_lang,
        "translation_applied": False,
        "sample_rate_hz": DEFAULT_DUB_SAMPLE_RATE_HZ,
        "sample_count": len(job.pcm),
        "duration_seconds": len(job.pcm) / DEFAULT_DUB_SAMPLE_RATE_HZ,
        "cues": job.cue_proofs,
        "mastering_status": "not_applied",
        "human_review_required": True,
        "media": {name: {"bytes": len(data), "sha256": _sha(data)} for name, data in media.items()},
    }
    if job.request.schema_version == 2:
        receipt.update(schema_version=2, request_schema_version=2, spatial=_spatial_evidence(job))
    remaining(job.deadline)
    with os.fdopen(os.dup(job.stage_fd), "w+b") as destination:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in sorted({**media, "receipt.json": _encoded(receipt)}.items()):
                remaining(job.deadline)
                archive.writestr(zipfile.ZipInfo(name), data)
        destination.flush()
        os.fsync(destination.fileno())
        destination.seek(0)
        archive_hash = "sha256:" + hashlib.file_digest(destination, "sha256").hexdigest()
    remaining(job.deadline)
    result = {
        "ok": True,
        "demo": False,
        "output_path": job.request.output_path,
        "output_sha256": archive_hash,
        "request_hash": job.request.canonical_id(),
        "backend": receipt["backend"],
        "cue_count": len(job.cues),
        "sample_count": len(job.pcm),
        "sample_rate_hz": DEFAULT_DUB_SAMPLE_RATE_HZ,
        "duration_seconds": receipt["duration_seconds"],
        "translation_applied": False,
        "mastering_status": "not_applied",
        "human_review_required": True,
    }
    if job.request.schema_version == 2:
        result.update(
            request_schema_version=2,
            spatial_profile=job.request.spatial_profile,
            spatial_sha256=canonical_digest(receipt["spatial"]),
        )
    return result


def finish_bundle(job) -> dict:
    result = _prepare_bundle(job)
    job.close_workspace()
    remaining(job.deadline)
    publish(job.parent_fd, job.stage_name, job.output_name)
    return result
