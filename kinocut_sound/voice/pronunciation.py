"""Project pronunciation dictionary — hash-keyed, no raw term text.

A :class:`PronunciationDictionary` resolves project-specific term overrides
keyed by the term's bounded SHA-256 hash. Raw term text is never stored on
the dictionary or carried in a serialized receipt: a :class:`Line`'s
``text_hash`` is the only handle the renderer needs to look up an override.

The dictionary is bounded (max 256 entries) and fail-closed: an unknown or
malformed override yields :class:`VoiceError(code=PRONUNCIATION_INVALID)`
rather than a silent fallback. Override values must satisfy the same IPA
bounds as :class:`kinocut_sound.PronunciationOverride` (no whitespace, no
path separators, at most 64 chars).

Design references (sonic-world design):
* M1 — Voice Generation: pronunciation dictionary (W1.7).
* Privacy & security — terms are hashes only.
"""

from __future__ import annotations

from collections.abc import Mapping
from itertools import islice
from types import MappingProxyType

from pydantic import ValidationError

from kinocut_sound._canonical import Sha256
from kinocut_sound.lines import PronunciationOverride

from kinocut_sound.voice._errors import (
    PRONUNCIATION_INVALID,
    bounded_voice_error,
    voice_error,
)

# --- Voice-leaf private ceiling ---
# TODO(controller): consider promoting to ``kinocut_sound/limits.py`` if S6/S10
# need a shared pronunciation-dictionary ceiling.
MAX_DICTIONARY_ENTRIES: int = 256


class PronunciationDictionary:
    """Hash-keyed project pronunciation overrides.

    ``overrides`` is a mapping from term hash (``sha256:<hex>``) to a bounded
    :class:`PronunciationOverride`. The mapping is copied into a sealed
    ``MappingProxyType`` so a later mutation cannot silently change which
    overrides resolve. The dictionary stores no raw term text — only hashes.
    """

    __slots__ = ("_overrides",)

    def __init__(self, overrides: Mapping[str, PronunciationOverride] | None = None) -> None:
        if overrides is None:
            source: dict[str, PronunciationOverride] = {}
        else:
            if not isinstance(overrides, Mapping):
                raise voice_error(
                    "pronunciation overrides must be a mapping",
                    PRONUNCIATION_INVALID,
                )
            try:
                bounded = tuple(islice(overrides.items(), MAX_DICTIONARY_ENTRIES + 1))
            except Exception as exc:
                raise voice_error(
                    "pronunciation overrides are not iterable",
                    PRONUNCIATION_INVALID,
                ) from exc
            if len(bounded) > MAX_DICTIONARY_ENTRIES:
                raise bounded_voice_error(
                    "pronunciation dictionary exceeds its ceiling",
                    PRONUNCIATION_INVALID,
                )
            source = {}
            for raw_key, raw_value in bounded:
                key, override = self._validate_entry(raw_key, raw_value)
                if override.term_hash != key:
                    raise voice_error(
                        "pronunciation override key must match term hash",
                        PRONUNCIATION_INVALID,
                    ) from None
                if key in source:
                    raise voice_error(
                        "pronunciation overrides must be unique by term hash",
                        PRONUNCIATION_INVALID,
                    ) from None
                source[key] = override
        self._overrides: Mapping[str, PronunciationOverride] = MappingProxyType(source)

    @staticmethod
    def _validate_entry(raw_key: object, raw_value: object) -> tuple[str, PronunciationOverride]:
        if not isinstance(raw_key, str):
            raise voice_error(
                "pronunciation override key must be a sha256 string",
                PRONUNCIATION_INVALID,
            ) from None
        if not raw_key.startswith("sha256:") or len(raw_key) != 71:
            raise voice_error(
                "pronunciation override key must be a sha256 term hash",
                PRONUNCIATION_INVALID,
            ) from None
        try:
            int(raw_key.removeprefix("sha256:"), 16)
        except ValueError as exc:
            raise voice_error(
                "pronunciation override key must be hex sha256",
                PRONUNCIATION_INVALID,
            ) from exc
        if isinstance(raw_value, PronunciationOverride):
            candidate = raw_value
        else:
            try:
                candidate = PronunciationOverride.model_validate(raw_value)
            except (ValidationError, TypeError) as exc:
                raise voice_error(
                    "pronunciation override value must be a PronunciationOverride",
                    PRONUNCIATION_INVALID,
                ) from exc
        # Re-validate so a model_construct bypass cannot smuggle prose in.
        PronunciationOverride.model_validate(candidate.model_dump(mode="python"))
        return raw_key, candidate

    @property
    def count(self) -> int:
        """Return the number of overrides compiled into the dictionary."""

        return len(self._overrides)

    @property
    def term_hashes(self) -> tuple[str, ...]:
        """Return the sorted sealed term hashes."""

        return tuple(sorted(self._overrides))

    def contains(self, term_hash: str) -> bool:
        """Return whether ``term_hash`` has an override on this dictionary."""

        return term_hash in self._overrides

    def resolve(self, term_hash: str) -> PronunciationOverride | None:
        """Return the override for ``term_hash`` or ``None`` if not present.

        Unknown term hashes are *not* errors: a project may carry overrides
        for terms that never appear in a given line. Callers requiring an
        override should check the returned value explicitly.
        """

        if not isinstance(term_hash, str):
            raise voice_error(
                "term hash must be a sha256 string",
                PRONUNCIATION_INVALID,
            ) from None
        return self._overrides.get(term_hash)

    def require(self, term_hash: str) -> PronunciationOverride:
        """Return the override for ``term_hash``; raise if absent."""

        override = self.resolve(term_hash)
        if override is None:
            raise bounded_voice_error(
                "pronunciation override is not registered",
                PRONUNCIATION_INVALID,
            )
        return override

    def merge(self, other: PronunciationDictionary) -> PronunciationDictionary:
        """Return a new dictionary with overrides from both dictionaries.

        Raises on overlapping term hashes — pronunciation overrides are
        versioned and unique by design, so a silent overwrite is prohibited.
        """

        if not isinstance(other, PronunciationDictionary):
            raise voice_error(
                "merge requires another PronunciationDictionary",
                PRONUNCIATION_INVALID,
            ) from None
        overlap = set(self._overrides) & set(other._overrides)
        if overlap:
            raise voice_error(
                "pronunciation dictionaries overlap",
                PRONUNCIATION_INVALID,
            ) from None
        merged: dict[str, PronunciationOverride] = dict(self._overrides)
        merged.update(other._overrides)
        return PronunciationDictionary(merged)

    def overrides_payload(self) -> dict[str, object]:
        """Return a canonical, sorted JSON payload for this dictionary."""

        return {
            "kind": "pronunciation_dictionary",
            "entries": [
                {"term_hash": key, "ipa": value.ipa} for key in self.term_hashes for value in (self._overrides[key],)
            ],
        }

    def term_hashes_for(self, line_pronunciation: object) -> tuple[Sha256, ...]:
        """Return the term hashes from a Line's pronunciation overrides."""

        try:
            items = tuple(iter(line_pronunciation))
        except TypeError as exc:
            raise voice_error(
                "line pronunciation overrides must be iterable",
                PRONUNCIATION_INVALID,
            ) from exc
        out: list[Sha256] = []
        for item in items:
            if isinstance(item, PronunciationOverride):
                out.append(item.term_hash)
                continue
            try:
                out.append(PronunciationOverride.model_validate(item).term_hash)
            except (ValidationError, TypeError) as exc:
                raise voice_error(
                    "line pronunciation override is invalid",
                    PRONUNCIATION_INVALID,
                ) from exc
        if len(set(out)) != len(out):
            raise voice_error(
                "line pronunciation overrides must be unique by term hash",
                PRONUNCIATION_INVALID,
            ) from None
        return tuple(out)
