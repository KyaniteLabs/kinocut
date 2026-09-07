"""Caller-supplied RIFF containers must be parsed structurally, not by search."""

from array import array
import struct

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav


def _chunk(kind, data):
    return kind + struct.pack("<I", len(data)) + data + (b"\0" if len(data) % 2 else b"")


def _riff(*chunks):
    body = b"WAVE" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _fmt(**overrides):
    values = dict(tag=1, channels=1, rate=22050, byte_rate=44100, align=2, bits=16)
    values.update(overrides)
    return _chunk(b"fmt ", struct.pack("<HHIIHH", *values.values()))


def test_metadata_data_text_and_odd_padding_are_not_audio_chunks():
    wav = _riff(_chunk(b"JUNK", b"data\xff"), _fmt(), _chunk(b"data", b"\x01\0\x02\0"))
    samples, rate = parse_wav(wav)
    assert list(samples) == [1, 2]
    assert rate == 22050


@pytest.mark.parametrize(
    "wav",
    [
        _riff(_fmt(tag=3), _chunk(b"data", b"\0\0")),
        _riff(_fmt(rate=0, byte_rate=0), _chunk(b"data", b"\0\0")),
        _riff(_fmt(align=4), _chunk(b"data", b"\0\0")),
        _riff(_fmt(byte_rate=1), _chunk(b"data", b"\0\0")),
        _riff(_fmt(), _chunk(b"data", b"\0")),
        _riff(_fmt(), _chunk(b"data", b"\0\0"), _chunk(b"data", b"\0\0")),
        _riff(_fmt(), _fmt(), _chunk(b"data", b"\0\0")),
        _riff(_fmt(), b"data" + struct.pack("<I", 100) + b"\0\0"),
        _riff(_fmt(), _chunk(b"data", b"\0\0"))[:-1],
        _riff(_fmt(), _chunk(b"data", b"\0\0")) + b"trailing",
    ],
)
def test_malformed_wav_is_a_typed_failure(wav):
    with pytest.raises(MixError):
        parse_wav(wav)


def test_pcm_boundary_values_roundtrip():
    expected = array("h", [-32768, -1, 0, 1, 32767])
    samples, rate = parse_wav(pcm_to_wav(expected, sample_rate_hz=48000))
    assert samples == expected
    assert rate == 48000
