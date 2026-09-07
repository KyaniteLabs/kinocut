"""Bounded real-ASR request; hashes bind audio and plain reference text."""

from typing import Literal

from pydantic import ValidationError, field_validator

from kinocut_sound._canonical import FrozenModel, canonical_digest
from kinocut_sound._errors import SoundContractError
from kinocut_sound.public.mix_request import SourceAsset, _json_payload, relative_path


class AsrError(SoundContractError):
    """A bounded speech-recognition failure."""


def asr_error(message, code="asr_input_invalid"):
    return AsrError(message, code=code)


class SoundAsrRequest(FrozenModel):
    schema_version: Literal[1] = 1
    source: SourceAsset
    reference: SourceAsset
    output_path: str
    language: Literal["en", "es"]
    model: Literal["base.en", "base"]

    _output = field_validator("output_path")(relative_path)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _version(cls, value):
        if type(value) is not int:
            raise asr_error("ASR schema version must be integer 1")
        return value

    def canonical_id(self):
        return canonical_digest(self.model_dump(mode="json"))


def load_asr_request(value, project_root):
    if not isinstance(project_root, str) or not project_root.strip():
        raise asr_error("ASR requires an explicit nonempty project root")
    try:
        if isinstance(value, SoundAsrRequest):
            value = value.model_dump(mode="json")
        request = SoundAsrRequest.model_validate(_json_payload(value))
    except (ValidationError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise asr_error("invalid ASR request") from exc
    if request.model == "base.en" and request.language != "en":
        raise asr_error("English-only model cannot recognize Spanish")
    return request


def real_mode(arguments):
    if set(arguments) - {"request", "project_root", "script_hashes", "audio_duration_seconds", "available"}:
        raise asr_error("unknown ASR arguments")
    real = "request" in arguments or "project_root" in arguments
    if real:
        if arguments.get("request") is None or not arguments.get("project_root"):
            raise asr_error("real ASR requires request and project_root")
        duration = arguments.get("audio_duration_seconds", 1.0)
        if arguments.get("script_hashes") is not None or type(duration) not in (int, float) or duration != 1.0:
            raise asr_error("real ASR cannot use legacy script hashes or duration")
        if arguments.get("available", True) is not True:
            raise asr_error("real ASR cannot use simulated availability")
    return real
