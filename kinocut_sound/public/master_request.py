"""Persisted measured-mastering intent for one supplied mono or stereo mix."""

from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator

from kinocut_sound._canonical import FrozenModel, canonical_digest
from kinocut_sound._errors import SoundContractError
from kinocut_sound.defaults import DEFAULT_MASTER_PEAK_MARGIN_DB
from kinocut_sound.delivery import DeliveryPolicy, StemRecombinationPolicy
from kinocut_sound.limits import MAX_MIX_SAMPLE_RATE_HZ, MIN_MIX_SAMPLE_RATE_HZ
from kinocut_sound.public.mix_request import SourceAsset, _json_payload, relative_path
from kinocut_sound.validation import FFMPEG_MASTER_LUFS_RANGE, FFMPEG_MASTER_PEAK_RANGE


class MasterError(SoundContractError):
    """Typed bounded mastering failure with no raw backend diagnostics."""


def master_error(message, code):
    return MasterError(message, code=code)


class SoundMasterRequest(FrozenModel):
    schema_version: Literal[1] = 1
    source: SourceAsset
    output_path: str
    delivery: DeliveryPolicy = Field(default_factory=DeliveryPolicy)
    output_sample_rate_hz: int | None = Field(
        default=None, strict=True, ge=MIN_MIX_SAMPLE_RATE_HZ, le=MAX_MIX_SAMPLE_RATE_HZ
    )

    _output = field_validator("output_path")(relative_path)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _version(cls, value):
        if type(value) is not int:
            raise master_error("master request version must be integer 1", "master_input_invalid")
        return value

    def canonical_id(self):
        return canonical_digest(self.model_dump(mode="json"))


def internal_peak(policy):
    ceiling = min(policy.loudness.true_peak_dbtp, policy.true_peak_ceiling_dbtp)
    return max(FFMPEG_MASTER_PEAK_RANGE[0], ceiling - DEFAULT_MASTER_PEAK_MARGIN_DB)


def load_master_request(value: Any, project_root):
    if not isinstance(project_root, str) or not project_root.strip():
        raise master_error("mastering requires an explicit nonempty project root", "master_input_invalid")
    try:
        if isinstance(value, SoundMasterRequest):
            value = value.model_dump(mode="json")
        request = SoundMasterRequest.model_validate(_json_payload(value))
    except (ValidationError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise master_error("invalid mastering request", "master_input_invalid") from exc
    policy = request.delivery
    if (
        policy.stems.stem_ids
        or policy.recombination != StemRecombinationPolicy()
        or policy.metadata_codes
        or policy.master_only_limiting_enabled
    ):
        raise master_error(
            "mastering supports one mono or stereo mix without stem or metadata intent", "master_unsupported_intent"
        )
    ceiling = min(policy.loudness.true_peak_dbtp, policy.true_peak_ceiling_dbtp)
    if not FFMPEG_MASTER_LUFS_RANGE[0] <= policy.loudness.integrated_lufs <= FFMPEG_MASTER_LUFS_RANGE[1] or not (
        FFMPEG_MASTER_PEAK_RANGE[0] <= ceiling <= FFMPEG_MASTER_PEAK_RANGE[1]
    ):
        raise master_error("mastering target is outside FFmpeg's supported range", "master_unsupported_intent")
    return request
