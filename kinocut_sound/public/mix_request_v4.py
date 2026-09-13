"""Explicit guarded rate conversion without changing older request shapes."""

from enum import StrEnum
from typing import Literal

from kinocut_sound._canonical import FrozenModel
from kinocut_sound.public.mix_request_v3 import SoundMixRequestV3


class ResamplingProfile(StrEnum):
    SOXR_VHQ_PCM16_GUARDED_V1 = "soxr_vhq_pcm16_guarded_v1"


class SourceResampling(FrozenModel):
    profile: ResamplingProfile


class SoundMixRequestV4(SoundMixRequestV3):
    schema_version: Literal[4] = 4
    source_resampling: SourceResampling
