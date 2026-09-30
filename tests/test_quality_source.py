"""Source uncertainty cannot silently select a range policy or become cached."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from kinocut.quality_guardrails import VisualQualityGuardrails
from kinocut.errors import ProcessingError


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        {},
        {"streams": []},
        {"streams": [None]},
        {"streams": [{}]},
        {"streams": [{"codec_type": ""}]},
        {"streams": [{"codec_type": "video"}]},
    ],
)
def test_invalid_source_metadata_is_unavailable_and_retried(tmp_path, monkeypatch, invalid):
    source = tmp_path / "clip.mkv"
    source.write_bytes(b"source")
    metadata = Mock(side_effect=[invalid, {"streams": [{"codec_type": "video", "pix_fmt": "gray10le"}]}])
    monkeypatch.setattr("kinocut.quality_source._run_ffprobe_json", metadata)
    measurements = Mock(
        return_value=subprocess.CompletedProcess(
            [],
            0,
            json.dumps({"frames": [{"pix_fmt": "yuv444p10le", "tags": {"lavfi.signalstats.YAVG": "512"}}]}),
            "",
        )
    )
    monkeypatch.setattr("kinocut.quality_guardrails.subprocess.run", measurements)
    guardrails = VisualQualityGuardrails()
    assert guardrails._get_all_signalstats(str(source)) == {}
    assert measurements.call_count == 0
    assert not guardrails._quality_source_cache
    assert guardrails._get_all_signalstats(str(source)) == {"lavfi.signalstats.YAVG": 128}
    assert metadata.call_count == 2
    assert measurements.call_count == 1
    assert ",setparams=range=full,signalstats" in measurements.call_args.args[0][6]


def test_metadata_processing_failure_has_unavailable_audio_and_measurement(monkeypatch):
    monkeypatch.setattr(
        "kinocut.quality_source._run_ffprobe_json", Mock(side_effect=ProcessingError("ffprobe", 1, "unusable"))
    )
    guardrails = VisualQualityGuardrails()
    assert guardrails._has_audio_stream("unusable") is None
    assert "_error" in guardrails._run_ffprobe("unusable", "lavfi.signalstats.YAVG")
    assert "_error" in guardrails._measure_temporal_motion("unusable")
    assert guardrails._run_ffmpeg_signalstats("unusable") == {}


def test_mixed_grayscale_and_color_streams_are_ambiguous(monkeypatch):
    monkeypatch.setattr(
        "kinocut.quality_source._run_ffprobe_json",
        lambda source: {
            "streams": [
                {"codec_type": "video", "pix_fmt": "gray10le"},
                {"codec_type": "video", "pix_fmt": "yuv420p"},
            ]
        },
    )
    measurements = Mock()
    monkeypatch.setattr("kinocut.quality_guardrails.subprocess.run", measurements)
    assert VisualQualityGuardrails()._get_all_signalstats("ambiguous") == {}
    assert measurements.call_count == 0
