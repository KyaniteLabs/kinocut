"""Strict, hashed plain-caption requests for optional local stock speech."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
import unicodedata

from pydantic import ValidationError, field_validator

from kinocut_sound._canonical import FrozenModel, canonical_digest
from kinocut_sound.captions import _CUE_SPLIT, _TS, _parse_srt
from kinocut_sound.limits import (
    MAX_DUB_CAPTION_BYTES,
    MAX_DUB_CUES,
    MAX_DUB_CUE_CHARS,
    MAX_DUB_TIMELINE_SECONDS,
    MAX_DUB_TOTAL_CHARS,
)
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error
from kinocut_sound.public.mix_request import SourceAsset, _json_payload, relative_path


class SoundDubRequest(FrozenModel):
    schema_version: Literal[1] = 1
    source: SourceAsset
    target_lang: Literal["en", "es"] = "es"
    voice: Literal["en-us", "es"] | None = None
    output_path: str

    _output = field_validator("output_path")(relative_path)

    @field_validator("schema_version", mode="before")
    @classmethod
    def _version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise mix_error("dub request version must be integer 1", MIX_INPUT_INVALID)
        return value

    @property
    def selected_voice(self) -> str:
        return "en-us" if self.target_lang == "en" else "es"

    def canonical_id(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))


def load_dub_request(value: Any) -> SoundDubRequest:
    try:
        if isinstance(value, SoundDubRequest):
            value = value.model_dump(mode="json")
        request = SoundDubRequest.model_validate(_json_payload(value))
        if request.voice is not None and request.voice != request.selected_voice:
            raise mix_error("stock voice must match target pronunciation language", MIX_INPUT_INVALID)
        return request
    except (ValidationError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise mix_error("invalid local caption speech request", MIX_INPUT_INVALID) from exc


@dataclass(frozen=True)
class CaptionCue:
    start_ms: int
    end_ms: int
    text: str


def _milliseconds(value: str) -> int:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    seconds, milliseconds = seconds.split(".")
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise mix_error("caption minute/second field out of range", MIX_INPUT_INVALID)
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(milliseconds)


def _validate_blocks(text: str) -> None:
    blocks = _CUE_SPLIT.split(text.strip())
    if not text.strip() or len(blocks) > MAX_DUB_CUES:
        raise mix_error("caption file requires a bounded nonempty cue list", MIX_OVER_LIMIT)
    for index, block in enumerate(blocks, start=1):
        lines = block.strip().splitlines()
        if lines and lines[0].isdigit():
            number = lines.pop(0)
            if not number.isascii() or number.lstrip("0") != str(index):
                raise mix_error("caption indices must be sequential ASCII numbers", MIX_INPUT_INVALID)
        if len(lines) < 2 or _TS.fullmatch(lines[0]) is None:
            raise mix_error("every caption block needs an exact timestamp and body", MIX_INPUT_INVALID)


def parse_captions(raw: bytes) -> tuple[CaptionCue, ...]:
    if len(raw) > MAX_DUB_CAPTION_BYTES:
        raise mix_error("caption file exceeds byte ceiling", MIX_OVER_LIMIT)
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeError as exc:
        raise mix_error("caption file must be UTF-8", MIX_INPUT_INVALID) from exc
    if any(unicodedata.category(char).startswith("C") and char not in "\n\t" for char in text):
        raise mix_error("caption control characters are unsupported", MIX_INPUT_INVALID)
    _validate_blocks(text)
    result = []
    total_chars = previous_end = 0
    for start, end, body in _parse_srt(text):
        start_ms, end_ms = _milliseconds(start), _milliseconds(end)
        if start_ms < previous_end or end_ms <= start_ms:
            raise mix_error("caption windows must be positive, ordered and nonoverlapping", MIX_INPUT_INVALID)
        if end_ms > MAX_DUB_TIMELINE_SECONDS * 1000:
            raise mix_error("caption timeline exceeds duration ceiling", MIX_OVER_LIMIT)
        if not body or any(marker in body for marker in ("<", ">", "[[", "]]")):
            raise mix_error("captions must be plain text, without markup or phoneme instructions", MIX_INPUT_INVALID)
        total_chars += len(body)
        if len(body) > MAX_DUB_CUE_CHARS or total_chars > MAX_DUB_TOTAL_CHARS:
            raise mix_error("caption text exceeds synthesis ceiling", MIX_OVER_LIMIT)
        result.append(CaptionCue(start_ms, end_ms, body))
        previous_end = end_ms
    return tuple(result)
