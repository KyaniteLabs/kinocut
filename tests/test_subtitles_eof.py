"""EOF-clamp coverage for subtitle/ASR segment lists (Plan 01 Task 3).

``clamp_segments_to_eof`` is a pure, FFmpeg-free helper reused by subtitle
generation, burn-in, and ASR. It trims segments that overshoot the media end,
drops segments that begin at or past it, leaves exactly-ending segments alone,
and validates its whole input strictly and atomically. It accepts both bare
``(start, end)`` pairs and mapping records (``{"start", "end", ...}``) whose
non-time fields are preserved immutably; the result segments are read-only
mappings. Warnings are a closed :class:`ClampWarning` enum.

Every test here is prefixed ``test_eof_`` so the mandated ``-k eof`` gate runs
the entire contract.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pytest

from kinocut.errors import MCPVideoError
from kinocut.subtitles_eof import (
    ClampedSegment,
    ClampWarning,
    EofClampResult,
    clamp_segments_to_eof,
)


class _Opaque:
    """A non-JSON-like object used to prove unsupported metadata is rejected."""


# --------------------------------------------------------------------------- #
# Pair segments
# --------------------------------------------------------------------------- #


def test_eof_overshoot_pair_is_clamped_with_warning():
    result = clamp_segments_to_eof([(0, 5), (5, 999)], eof_seconds=8.0)
    assert [(s.start, s.end) for s in result.segments] == [(0.0, 5.0), (5.0, 8.0)]
    assert result.clamped == 1
    assert result.warnings == (ClampWarning.CLAMPED,)


def test_eof_exact_eof_pair_is_not_clamped():
    result = clamp_segments_to_eof([(0, 8)], eof_seconds=8.0)
    assert [(s.start, s.end) for s in result.segments] == [(0.0, 8.0)]
    assert result.clamped == 0
    assert result.warnings == ()


def test_eof_pair_wholly_after_eof_is_dropped():
    result = clamp_segments_to_eof([(0, 5), (9, 12)], eof_seconds=8.0)
    assert [(s.start, s.end) for s in result.segments] == [(0.0, 5.0)]
    assert result.dropped == 1
    assert result.warnings == (ClampWarning.DROPPED,)


def test_eof_pair_starting_exactly_at_eof_is_dropped():
    result = clamp_segments_to_eof([(8, 10)], eof_seconds=8.0)
    assert result.segments == ()
    assert result.dropped == 1


def test_eof_pair_segment_has_empty_immutable_fields():
    result = clamp_segments_to_eof([(0, 5)], eof_seconds=8.0)
    seg = result.segments[0]
    assert seg.fields == {}
    with pytest.raises(TypeError):
        seg.fields["x"] = 1  # read-only mapping view


def test_eof_input_list_is_not_mutated():
    segments = [(0, 5), (5, 999)]
    original = list(segments)
    clamp_segments_to_eof(segments, eof_seconds=8.0)
    assert segments == original


def test_eof_result_and_segment_are_frozen():
    result = clamp_segments_to_eof([(0, 5)], eof_seconds=8.0)
    assert isinstance(result, EofClampResult)
    assert isinstance(result.segments[0], ClampedSegment)
    with pytest.raises((AttributeError, TypeError)):
        result.segments = ()
    with pytest.raises((AttributeError, TypeError)):
        result.segments[0].start = 0.0


def test_eof_no_segments_yields_empty_result():
    result = clamp_segments_to_eof([], eof_seconds=8.0)
    assert result.segments == ()
    assert result.warnings == ()
    assert (result.clamped, result.dropped) == (0, 0)


def test_eof_ordering_and_determinism_preserved():
    result = clamp_segments_to_eof([(0, 2), (2, 4), (4, 999), (999, 1000)], eof_seconds=5.0)
    assert [(s.start, s.end) for s in result.segments] == [(0.0, 2.0), (2.0, 4.0), (4.0, 5.0)]


def test_eof_combined_clamp_and_drop_are_deterministic():
    # Chronological, non-overlapping: (5,999) overshoots -> clamped;
    # (999,1000) begins after EOF -> dropped. Warning order is stable.
    result = clamp_segments_to_eof([(0, 5), (5, 999), (999, 1000)], eof_seconds=8.0)
    assert [(s.start, s.end) for s in result.segments] == [(0.0, 5.0), (5.0, 8.0)]
    assert result.warnings == (ClampWarning.CLAMPED, ClampWarning.DROPPED)
    assert (result.clamped, result.dropped) == (1, 1)


# --------------------------------------------------------------------------- #
# Read-only Mapping interface
# --------------------------------------------------------------------------- #


def test_eof_segment_is_readonly_mapping_with_get():
    result = clamp_segments_to_eof([{"start": 0, "end": 5, "text": "hi"}], eof_seconds=8.0)
    seg = result.segments[0]
    assert isinstance(seg, Mapping)
    assert seg["start"] == 0.0
    assert seg["end"] == 5.0
    assert seg["text"] == "hi"
    assert seg.get("start") == 0.0
    assert seg.get("text") == "hi"
    assert seg.get("missing") is None
    with pytest.raises(TypeError):
        seg["text"] = "changed"  # read-only mapping


def test_eof_segment_mapping_len_and_iter():
    result = clamp_segments_to_eof([{"start": 0, "end": 5, "text": "hi", "spk": "A"}], eof_seconds=8.0)
    seg = result.segments[0]
    assert len(seg) == 4
    assert set(seg) == {"start", "end", "text", "spk"}
    assert dict(seg) == {"start": 0.0, "end": 5.0, "text": "hi", "spk": "A"}


# --------------------------------------------------------------------------- #
# Direct construction must be as safe as the factory
# --------------------------------------------------------------------------- #


def test_eof_direct_segment_construction_freezes_nested_fields():
    # Constructing a ClampedSegment directly must snapshot+freeze fields, not
    # store the caller's mutable structure verbatim.
    words = ["a", "b"]
    seg = ClampedSegment(0.0, 5.0, {"words": words})
    assert seg.fields["words"] == ("a", "b")
    with pytest.raises(AttributeError):
        seg.fields["words"].append("c")  # frozen to an immutable sequence
    words.append("c")  # caller mutation must not bleed into the segment
    assert seg.fields["words"] == ("a", "b")


def test_eof_direct_segment_construction_is_read_only_mapping():
    seg = ClampedSegment(0.0, 5.0, {"text": "hi"})
    assert isinstance(seg, Mapping)
    assert seg.get("start") == 0.0
    assert seg.get("text") == "hi"
    with pytest.raises(TypeError):
        seg.fields["text"] = "changed"


def test_eof_direct_segment_construction_rejects_non_string_keys():
    with pytest.raises(MCPVideoError) as excinfo:
        ClampedSegment(0.0, 5.0, {1: "x"})
    assert excinfo.value.code == "invalid_eof_clamp"


def test_eof_direct_segment_construction_rejects_bad_metadata():
    for bad_fields in ({"x": {"a"}}, {"c": math.inf}):
        with pytest.raises(MCPVideoError) as excinfo:
            ClampedSegment(0.0, 5.0, bad_fields)
        assert excinfo.value.code == "invalid_eof_clamp"


def test_eof_direct_segment_construction_rejects_reserved_keys():
    # Fields shadowing the reserved time keys would duplicate iteration and
    # break the len/iteration invariant; reject them at construction.
    for reserved in ("start", "end"):
        with pytest.raises(MCPVideoError) as excinfo:
            ClampedSegment(0.0, 5.0, {reserved: 1})
        assert excinfo.value.code == "invalid_eof_clamp"


def test_eof_segment_mapping_iteration_is_consistent():
    result = clamp_segments_to_eof([{"start": 0, "end": 5, "text": "hi", "spk": "A"}], eof_seconds=8.0)
    seg = result.segments[0]
    keys = list(seg)
    assert len(keys) == len(set(keys)) == len(seg)  # no duplicates; len matches iter
    assert {k: seg[k] for k in seg} == dict(seg)


# --------------------------------------------------------------------------- #
# Mapping (record) segments — preserve non-time fields immutably
# --------------------------------------------------------------------------- #


def test_eof_mapping_segment_is_clamped_and_preserves_fields():
    result = clamp_segments_to_eof([{"start": 0, "end": 999, "text": "hi", "speaker": "A"}], eof_seconds=8.0)
    seg = result.segments[0]
    assert (seg.start, seg.end) == (0.0, 8.0)
    assert seg.fields == {"text": "hi", "speaker": "A"}
    assert result.warnings == (ClampWarning.CLAMPED,)


def test_eof_mapping_fields_are_immutable_and_snapshot():
    source = {"start": 0, "end": 5, "text": "hi"}
    result = clamp_segments_to_eof([source], eof_seconds=8.0)
    seg = result.segments[0]
    with pytest.raises(TypeError):
        seg.fields["text"] = "changed"  # read-only view
    source["text"] = "mutated"
    assert seg.fields == {"text": "hi"}


def test_eof_mapping_input_dict_is_not_mutated():
    source = {"start": 0, "end": 999, "text": "hi"}
    original = dict(source)
    clamp_segments_to_eof([source], eof_seconds=8.0)
    assert source == original


def test_eof_mapping_wholly_after_eof_is_dropped():
    result = clamp_segments_to_eof([{"start": 9, "end": 12, "text": "late"}], eof_seconds=8.0)
    assert result.segments == ()
    assert result.dropped == 1
    assert result.warnings == (ClampWarning.DROPPED,)


def test_eof_nested_list_field_is_snapshot_and_immutable():
    # Real ASR records carry nested word lists; the snapshot must be deep so
    # neither the result nor the caller can mutate the other through it.
    source = {"start": 0, "end": 5, "words": ["a", "b"]}
    result = clamp_segments_to_eof([source], eof_seconds=8.0)
    words = result.segments[0].fields["words"]
    with pytest.raises(AttributeError):
        words.append("c")  # frozen to an immutable sequence
    source["words"].append("c")  # caller mutation must not bleed in
    assert result.segments[0].fields["words"] == ("a", "b")


def test_eof_nested_mapping_field_is_read_only_and_snapshot():
    source = {"start": 0, "end": 5, "meta": {"lang": "en"}}
    result = clamp_segments_to_eof([source], eof_seconds=8.0)
    meta = result.segments[0].fields["meta"]
    with pytest.raises(TypeError):
        meta["lang"] = "es"  # nested mapping is read-only
    source["meta"]["lang"] = "es"  # caller mutation must not bleed in
    assert result.segments[0].fields["meta"] == {"lang": "en"}


def test_eof_deeply_nested_metadata_is_fully_frozen():
    source = {"start": 0, "end": 5, "tokens": [{"w": "hi", "conf": [0.9]}]}
    result = clamp_segments_to_eof([source], eof_seconds=8.0)
    tokens = result.segments[0].fields["tokens"]
    assert tokens == ({"w": "hi", "conf": (0.9,)},)
    with pytest.raises(AttributeError):
        tokens[0]["conf"].append(0.1)  # innermost list frozen too
    with pytest.raises(TypeError):
        tokens[0]["w"] = "changed"  # inner mapping read-only


def test_eof_mixed_pair_and_mapping_inputs_are_supported():
    result = clamp_segments_to_eof([(0, 2), {"start": 2, "end": 999, "text": "x"}], eof_seconds=5.0)
    assert [(s.start, s.end) for s in result.segments] == [(0.0, 2.0), (2.0, 5.0)]
    assert result.segments[0].fields == {}
    assert result.segments[1].fields == {"text": "x"}


# --------------------------------------------------------------------------- #
# Metadata hardening — reject hostile / non-JSON-like metadata
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "segment",
    [
        {"start": 0, "end": 5, 7: "x"},  # top-level non-string key
        {"start": 0, "end": 5, "meta": {1: "x"}},  # nested non-string key
    ],
)
def test_eof_non_string_metadata_key_is_rejected(segment):
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([segment], eof_seconds=8.0)
    assert excinfo.value.code == "invalid_eof_clamp"


@pytest.mark.parametrize("bad", [{"a"}, _Opaque(), b"bytes", complex(1, 2)])
def test_eof_unsupported_metadata_type_is_rejected(bad):
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([{"start": 0, "end": 5, "x": bad}], eof_seconds=8.0)
    assert excinfo.value.code == "invalid_eof_clamp"


@pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
def test_eof_nonfinite_metadata_is_rejected(bad):
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([{"start": 0, "end": 5, "conf": bad}], eof_seconds=8.0)
    assert excinfo.value.code == "invalid_eof_clamp"


def test_eof_nested_nonfinite_metadata_is_rejected():
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([{"start": 0, "end": 5, "scores": [1.0, math.nan]}], eof_seconds=8.0)
    assert excinfo.value.code == "invalid_eof_clamp"


def test_eof_cyclic_mapping_metadata_is_rejected():
    meta = {"k": 1}
    meta["self"] = meta
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([{"start": 0, "end": 5, "meta": meta}], eof_seconds=8.0)
    assert excinfo.value.code == "invalid_eof_clamp"


def test_eof_cyclic_list_metadata_is_rejected():
    words = [1]
    words.append(words)
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([{"start": 0, "end": 5, "words": words}], eof_seconds=8.0)
    assert excinfo.value.code == "invalid_eof_clamp"


# --------------------------------------------------------------------------- #
# Closed StrEnum warnings
# --------------------------------------------------------------------------- #


def test_eof_warning_enum_has_exact_stable_codes():
    assert ClampWarning.CLAMPED == "segment_clamped_to_eof"
    assert ClampWarning.DROPPED == "segment_dropped_after_eof"
    assert {w.value for w in ClampWarning} == {
        "segment_clamped_to_eof",
        "segment_dropped_after_eof",
    }


def test_eof_warnings_are_enum_members_not_bare_strings():
    result = clamp_segments_to_eof([(0, 999)], eof_seconds=8.0)
    assert all(isinstance(w, ClampWarning) for w in result.warnings)


# --------------------------------------------------------------------------- #
# Cross-segment chronology
# --------------------------------------------------------------------------- #


def test_eof_out_of_order_segments_are_rejected():
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([(5, 10), (0, 3)], eof_seconds=20.0)
    assert excinfo.value.code == "invalid_eof_clamp"


def test_eof_overlapping_segments_are_rejected():
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([(0, 5), (3, 8)], eof_seconds=20.0)
    assert excinfo.value.code == "invalid_eof_clamp"


def test_eof_adjacent_segments_are_allowed():
    result = clamp_segments_to_eof([(0, 5), (5, 8)], eof_seconds=20.0)
    assert [(s.start, s.end) for s in result.segments] == [(0.0, 5.0), (5.0, 8.0)]


def test_eof_mixed_valid_and_invalid_input_fails_atomically():
    # A later invalid segment must abort the whole call — no partial result.
    with pytest.raises(MCPVideoError):
        clamp_segments_to_eof([(0, 5), (5, 2)], eof_seconds=8.0)


# --------------------------------------------------------------------------- #
# Top-level container validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("container", ["0,5", 5, {"start": 0, "end": 5}, None, (x for x in [])])
def test_eof_non_sequence_container_is_rejected(container):
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof(container, eof_seconds=8.0)
    assert excinfo.value.code == "invalid_eof_clamp"


# --------------------------------------------------------------------------- #
# Invalid EOF and invalid segment values
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("eof", [0.0, -1.0, math.inf, math.nan, "8", True, None])
def test_eof_invalid_eof_seconds_is_rejected(eof):
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([(0, 5)], eof_seconds=eof)
    assert excinfo.value.code == "invalid_eof_clamp"


@pytest.mark.parametrize(
    "segment",
    [
        (5, 2),  # start > end (misordered)
        (5, 5),  # zero length
        (-1, 5),  # negative start
        (0, math.inf),  # non-finite end
        (math.nan, 5),  # non-finite start
        (0,),  # wrong arity
        (0, 5, 9),  # wrong arity
        "0,5",  # wrong element type
        (True, 5),  # boolean not a real number
        {"end": 5},  # mapping missing start
        {"start": 0},  # mapping missing end
        {"start": math.nan, "end": 5},  # mapping non-finite start
        {"start": 0, "end": math.inf},  # mapping non-finite end
        {"start": 5, "end": 2},  # mapping misordered
    ],
)
def test_eof_invalid_segment_is_rejected(segment):
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([segment], eof_seconds=8.0)
    assert excinfo.value.code == "invalid_eof_clamp"


def test_eof_error_does_not_echo_raw_segment_values():
    # Build the hostile value by concatenation so the literal path never appears
    # in this source file (keeps the repo leak audit clean).
    hostile = "/" + "Users/victim/secret.mov"
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([(hostile, 5)], eof_seconds=8.0)
    assert hostile not in str(excinfo.value)


def test_eof_invalid_eof_value_is_not_echoed():
    hostile = "/" + "Volumes/Private/secret"
    with pytest.raises(MCPVideoError) as excinfo:
        clamp_segments_to_eof([(0, 5)], eof_seconds=hostile)
    assert hostile not in str(excinfo.value)
    assert excinfo.value.code == "invalid_eof_clamp"
