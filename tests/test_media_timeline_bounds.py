"""Failure paths must not certify incomplete or changing stream extents."""

from pathlib import Path

import pytest

from kinocut.engine_media_timeline import _packet_extent, _primary_audio_timeline
from kinocut.errors import MCPVideoError


def _producer(text, source=None):
    def write(args, **kwargs):
        assert kwargs["timeout"] > 0
        Path(args[args.index("-o") + 1]).write_text(text)
        if source is not None:
            source.write_bytes(b"changed source bytes")

    return write


def test_signed_pts_measures_presentation_not_decode_extent(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"fixture")
    timeline = _packet_extent(
        str(source),
        "v:0",
        runner=_producer("pts_time=-1|duration_time=0.04\npts_time=1|duration_time=0.04\n"),
    )
    assert timeline == pytest.approx((-1, 2.04))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "pts_time=N/A|duration_time=0.04\n",
        "pts_time=0|duration_time=0\n",
        "pts_time=inf|duration_time=0.04\n",
        "pts_time=0|duration_time=-1\n",
    ],
)
def test_unmeasurable_packets_fail_closed(tmp_path, text):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"fixture")
    with pytest.raises(MCPVideoError) as error:
        _packet_extent(str(source), "v:0", runner=_producer(text))
    assert error.value.code == "invalid_media_duration"


def test_changing_source_cannot_publish_a_stale_extent(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"fixture")
    with pytest.raises(MCPVideoError) as error:
        _packet_extent(str(source), "v:0", runner=_producer("pts_time=0|duration_time=1\n", source))
    assert error.value.code == "media_source_changed"


def test_audio_packet_sentinel_count_survives_undecodable_last_packet(tmp_path):
    source = tmp_path / "source.mka"
    source.write_bytes(b"fixture")
    # A decoder may drop a packet entirely. Counting only frames would accept
    # the partial extent and never notice the producer sentinel.
    text = "packet|pts_time=0\nframe|pts_time=0|nb_samples=1024\npacket|pts_time=0.02\n"
    with pytest.raises(MCPVideoError) as error:
        _packet_extent(str(source), "a:0", runner=_producer(text), audio_sample_rate=48000, packet_limit=1)
    assert error.value.code == "audio_mix_timeline_over_limit"


def test_audio_metadata_extent_uses_primary_stream_not_default_or_picture():
    probe = {
        "format": {"duration": "9"},
        "streams": [
            {"codec_type": "video", "duration": "9"},
            {"codec_type": "audio", "duration": "2", "start_time": "1"},
            {"codec_type": "audio", "duration": "8", "disposition": {"default": 1}},
        ],
    }
    assert _primary_audio_timeline("unused", probe) == (1, 2)
