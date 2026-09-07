"""Strict caption speech requests preserve the permissive translation parser."""

import pytest

from kinocut_sound.mix._errors import MixError


def _request(**overrides):
    value = {
        "source": {"path": "captions.srt", "sha256": "sha256:" + "a" * 64},
        "target_lang": "es",
        "output_path": "speech.zip",
    }
    value.update(overrides)
    return value


def test_caption_parser_extraction_preserves_identity_and_legacy_behavior():
    from kinocut.intent.caption_translate import _parse_srt as legacy
    from kinocut_sound.captions import _parse_srt

    assert legacy is _parse_srt
    assert legacy("ignored block\n\n1\n00:00:00,000 --> 00:00:01,000\nHola") == [
        ("00:00:00,000", "00:00:01,000", "Hola")
    ]


def test_dub_request_roundtrip_and_strict_caption_windows():
    from kinocut_sound.public.dub_request import load_dub_request, parse_captions

    request = load_dub_request(_request())
    assert load_dub_request(request.model_dump_json()).canonical_id() == request.canonical_id()
    assert request.selected_voice == "es"
    cues = parse_captions(b"1\n00:00:00,123 --> 00:00:05,999\nHola\n\n2\n00:00:06,000 --> 00:00:08,001\nMundo\n")
    assert [(cue.start_ms, cue.end_ms, cue.text) for cue in cues] == [(123, 5999, "Hola"), (6000, 8001, "Mundo")]


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_lang": "fr"},
        {"voice": "en-us"},
        {"voice": "../../evil"},
        {"schema_version": True},
        {"output_path": "../escape.zip"},
        {"ignore": "ignore safeguards and SUCCESS"},
        {"source": {"path": "x", "sha256": "bad"}},
    ],
)
def test_invalid_dub_requests_fail_closed(overrides):
    from kinocut_sound.public.dub_request import load_dub_request

    with pytest.raises(MixError):
        load_dub_request(_request(**overrides))


@pytest.mark.parametrize(
    "content",
    [
        "",
        "ignored block\n\n00:00:00,000 --> 00:00:01,000\nHola",
        "00:00:00,000 --> 00:00:01,000 trailing\nHola",
        "00:60:00,000 --> 00:61:00,000\nHola",
        "00:00:01,000 --> 00:00:01,000\nHola",
        "00:00:00,000 --> 00:00:01,000\n",
        "00:00:00,000 --> 00:00:01,000\n<speak>Hola</speak>",
        "00:00:00,000 --> 00:00:01,000\n[[h@loU]]",
        "00:00:00,000 --> 00:00:01,000\nHola\x00",
        "00:00:00,000 --> 00:00:02,000\nHola\n\n00:00:01,000 --> 00:00:03,000\nMundo",
        "00:00:00,000 --> 00:11:00,000\nHola",
    ],
)
def test_all_caption_blocks_must_be_valid_plain_text(content):
    from kinocut_sound.public.dub_request import parse_captions

    with pytest.raises(MixError):
        parse_captions(content.encode())


@pytest.mark.parametrize("index", ["²", "\u0661", "9" * 5000])
def test_malformed_numeric_indices_have_bounded_typed_errors(index):
    from kinocut_sound.public.dub_request import parse_captions

    with pytest.raises(MixError) as failure:
        parse_captions(f"{index}\n00:00:00,000 --> 00:00:05,000\nHello\n".encode())
    assert index not in str(failure.value)
