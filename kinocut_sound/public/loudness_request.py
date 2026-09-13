"""Read-only, hashed local-media loudness inspection through public surfaces."""

from dataclasses import asdict
import hashlib
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from kinocut_sound._canonical import FrozenModel, canonical_digest
from kinocut_sound.defaults import DEFAULT_LOUDNESS_DEMO_DURATION_SECONDS
from kinocut_sound.delivery import DeliveryPolicy
from kinocut_sound.limits import MAX_MIX_INPUT_BYTES
from kinocut_sound.mix._wav import synthesize_tone
from kinocut_sound.public.mix_files import open_root, read_asset
from kinocut_sound.public.mix_request import SourceAsset, _json_payload
from kinocut_sound.qa._errors import QA_INPUT_INVALID, qa_error
from kinocut_sound.qa.loudness import evaluate_loudness
from kinocut_sound.qa.meter import measure_with_identity, measure_with_identity_async, validate_material


class SoundLoudnessRequest(FrozenModel):
    schema_version: Literal[1] = 1
    source: SourceAsset
    delivery: DeliveryPolicy = Field(default_factory=DeliveryPolicy)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _version(cls, value):
        if type(value) is not int:
            raise qa_error("loudness request version must be integer 1", QA_INPUT_INVALID)
        return value


def _material(wav_bytes, request, project_root, delivery):
    if request is not None or project_root is not None:
        if not isinstance(project_root, str) or not project_root.strip():
            raise qa_error("loudness request requires an explicit nonempty project_root", QA_INPUT_INVALID)
        if wav_bytes is not None or delivery is not None:
            raise qa_error("loudness request and bytes modes conflict", QA_INPUT_INVALID)
        try:
            payload = request.model_dump(mode="json") if isinstance(request, SoundLoudnessRequest) else request
            model = SoundLoudnessRequest.model_validate(_json_payload(payload))
        except (ValidationError, TypeError, ValueError) as exc:
            raise qa_error("invalid loudness request", QA_INPUT_INVALID) from exc
        with open_root(project_root) as root:
            data = read_asset(root, model.source.path, model.source.sha256, MAX_MIX_INPUT_BYTES)
        return data, model.delivery, False
    try:
        policy_payload = delivery.model_dump() if isinstance(delivery, DeliveryPolicy) else delivery
        policy = DeliveryPolicy.model_validate({} if policy_payload is None else policy_payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise qa_error("invalid loudness delivery policy", QA_INPUT_INVALID) from exc
    demo = wav_bytes is None
    data = synthesize_tone(duration_seconds=DEFAULT_LOUDNESS_DEMO_DURATION_SECONDS, seed=1) if demo else wav_bytes
    return data, policy, demo


def _receipt(data, policy, demo, measurement):
    metrics, version = measurement
    report = evaluate_loudness(metrics, policy)
    receipt = {
        "artifact_kind": "sound_loudness_measurement",
        "demo": demo,
        "source_sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
        "policy_hash": canonical_digest(policy.model_dump(mode="json")),
        "meter": "ffmpeg_ebur128_true_peak",
        "backend_version": version,
        **asdict(report),
    }
    rate, frames, channels = validate_material(data)
    if channels == 2:
        receipt.update(
            schema_version=2,
            channel_count=channels,
            frame_count=frames,
            interleaved_sample_count=frames * channels,
            sample_rate_hz=rate,
        )
    return receipt


def inspect_loudness(wav_bytes=None, *, request=None, project_root=None, delivery=None):
    data, policy, demo = _material(wav_bytes, request, project_root, delivery)
    return _receipt(data, policy, demo, measure_with_identity(data))


async def inspect_loudness_async(*, request=None, project_root=None):
    data, policy, demo = _material(None, request, project_root, None)
    return _receipt(data, policy, demo, await measure_with_identity_async(data))
