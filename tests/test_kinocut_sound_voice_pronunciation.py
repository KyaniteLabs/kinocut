"""Pronunciation dictionary tests for the S5 voice leaf.

Covers W1.7 (project terms dictionary): hash-keyed overrides resolve, raw
term text is never stored, hostile mappings (unbounded prose, wrong shape,
overlapping merge) fail closed, and the dictionary fingerprint is stable
and bounded.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound import PronunciationOverride
from kinocut_sound.voice import (
    MAX_DICTIONARY_ENTRIES,
    PRONUNCIATION_INVALID,
    PronunciationDictionary,
    VoiceError,
)


_HEX_SEEDS: tuple[str, ...] = tuple("0123456789abcdef")


def _term_hash(seed: str) -> str:
    """Return a stable sha256 term hash for a single hex-character seed."""

    # The SHA256_PATTERN requires 64 hex chars; replicate the seed to fill.
    assert len(seed) == 1 and seed in _HEX_SEEDS, "seed must be a single hex char"
    return "sha256:" + (seed * 64)[:64]


def _override(seed: str, ipa: str = "ka.ton") -> PronunciationOverride:
    return PronunciationOverride(term_hash=_term_hash(seed), ipa=ipa)


def test_empty_dictionary_resolves_none_for_any_term():
    dictionary = PronunciationDictionary()
    assert dictionary.count == 0
    assert dictionary.resolve(_term_hash("a")) is None
    assert dictionary.contains(_term_hash("a")) is False


def test_dictionary_indexes_overrides_by_term_hash():
    override = _override("a", "ka.ton")
    dictionary = PronunciationDictionary({_term_hash("a"): override})
    assert dictionary.count == 1
    resolved = dictionary.resolve(_term_hash("a"))
    assert resolved is not None
    assert resolved.ipa == "ka.ton"


def test_dictionary_require_raises_for_missing_override():
    dictionary = PronunciationDictionary()
    with pytest.raises(VoiceError) as exc:
        dictionary.require(_term_hash("a"))
    assert exc.value.code == PRONUNCIATION_INVALID


def test_dictionary_rejects_non_sha256_keys_and_hostile_prose():
    override = _override("a")
    for bad_key in ("not-a-hash", "sha256:nothex", "sha256:" + "g" * 64, ""):
        with pytest.raises(VoiceError) as exc:
            PronunciationDictionary({bad_key: override})
        assert exc.value.code == PRONUNCIATION_INVALID


def test_dictionary_rejects_unbounded_ipa_and_path_like_values():
    override = _override("a")
    for bad_ipa in ("with space", "/etc/passwd", "a/b", "a\\b", "x" * 65):
        with pytest.raises(ValidationError):
            PronunciationOverride(term_hash=override.term_hash, ipa=bad_ipa)


def test_dictionary_rejects_overlapping_merge_silently():
    override_a = _override("a", "ka.ton")
    override_a_dup = _override("a", "ku.tun")
    left = PronunciationDictionary({_term_hash("a"): override_a})
    right = PronunciationDictionary({_term_hash("a"): override_a_dup})
    with pytest.raises(VoiceError) as exc:
        left.merge(right)
    assert exc.value.code == PRONUNCIATION_INVALID


def test_dictionary_merge_combines_disjoint_overrides():
    left = PronunciationDictionary({_term_hash("a"): _override("a", "ka.ton")})
    right = PronunciationDictionary({_term_hash("b"): _override("b", "tu.nu")})
    merged = left.merge(right)
    assert merged.count == 2
    assert merged.resolve(_term_hash("a")).ipa == "ka.ton"
    assert merged.resolve(_term_hash("b")).ipa == "tu.nu"


def test_dictionary_payload_is_stable_and_does_not_leak_raw_term_text():
    dictionary = PronunciationDictionary(
        {
            _term_hash("f"): _override("f", "fu.last"),
            _term_hash("a"): _override("a", "a.first"),
        }
    )
    payload = dictionary.overrides_payload()
    # Entries are sorted by hash; raw seed letters used in test do not appear.
    entries = payload["entries"]
    assert entries[0]["term_hash"] < entries[-1]["term_hash"]
    # Raw text never rides in (entries carry hashes only).
    for entry in entries:
        assert entry["term_hash"].startswith("sha256:")
        assert len(entry["term_hash"]) == 71


def test_dictionary_rejects_over_ceiling_input():
    # Build MAX_DICTIONARY_ENTRIES + 1 unique hex sha256 strings by varying
    # the first three hex characters (16^3 = 4096 distinct combinations).
    def _hash_for_index(index: int) -> str:
        a = _HEX_SEEDS[index % 16]
        b = _HEX_SEEDS[(index // 16) % 16]
        c = _HEX_SEEDS[(index // 256) % 16]
        return "sha256:" + (a + b + c).ljust(64, "0")

    too_many = {
        h: PronunciationOverride(term_hash=h, ipa=f"p{i % 16:x}")
        for i, h in enumerate(_hash_for_index(i) for i in range(MAX_DICTIONARY_ENTRIES + 1))
    }
    assert len(too_many) == MAX_DICTIONARY_ENTRIES + 1
    with pytest.raises(VoiceError) as exc:
        PronunciationDictionary(too_many)
    assert exc.value.code == PRONUNCIATION_INVALID


def test_dictionary_term_hashes_for_rejects_non_pronunciation_iterable_items():
    dictionary = PronunciationDictionary()
    with pytest.raises(VoiceError) as exc:
        dictionary.term_hashes_for(["not-an-object"])
    assert exc.value.code == PRONUNCIATION_INVALID


def test_dictionary_term_hashes_for_returns_unique_sorted_hashes():
    overrides = (
        _override("a", "ka.ton"),
        _override("b", "tu.nu"),
    )
    dictionary = PronunciationDictionary()
    hashes = dictionary.term_hashes_for(overrides)
    assert len(hashes) == 2
    assert len(set(hashes)) == 2
