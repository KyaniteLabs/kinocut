"""Public audio additions participate in Client aliases, contracts and guardrails."""

from unittest.mock import Mock

import pytest

from kinocut import Client
from kinocut.errors import MCPVideoError
from kinocut.models import EditResult


@pytest.mark.parametrize("method", ["mix_audio", "duck_audio"])
def test_audio_method_metadata_advertises_guarded_media_contract(method):
    client = Client()
    metadata = client.inspect(method)
    assert metadata["category"] == "media" and metadata["return_type"] == "EditResult"
    assert metadata["aliases"]["output"] == "output_path"
    assert metadata["aliases"]["video"] == "input_path"
    assert getattr(Client, method)._mcp_video_guarded


def test_mix_aliases_preserve_tracks_options_and_result(monkeypatch):
    tracks = [{"path": "voice.wav", "start": 1.25, "volume": 0.5}]
    expected = EditResult(output_path="out.mp4", warnings=["listen"])
    engine = Mock(return_value=expected)
    monkeypatch.setattr("kinocut.engine_audio_mix.mix_audio", engine)
    result = Client().mix_audio(
        input_path="in.mp4", tracks=tracks, output_path="out.mp4", keep_source=False, audio_bitrate="192k"
    )
    engine.assert_called_once_with("in.mp4", tracks, "out.mp4", keep_source=False, audio_bitrate="192k")
    assert result is expected and result.operation == "mix_audio" and result.warnings == ["listen"]


def test_duck_aliases_preserve_sidechain_parameters(monkeypatch):
    expected = EditResult(output_path="out.mp4")
    engine = Mock(return_value=expected)
    monkeypatch.setattr("kinocut.engine_audio_ops.duck_audio", engine)
    result = Client().duck_audio(
        input_path="in.mp4",
        music_path="music.wav",
        output_path="out.mp4",
        music_volume=0.4,
        threshold=0.03,
        ratio=6.0,
        attack=10.0,
        release=200.0,
    )
    engine.assert_called_once_with("in.mp4", "music.wav", "out.mp4", 0.4, 0.03, 6.0, 10.0, 200.0)
    assert result is expected and result.operation == "duck_audio"


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("mix_audio", {"video": "in.mp4", "tracks": [], "input_path": "other.mp4"}),
        ("mix_audio", {"video": "in.mp4", "tracks": [], "output": "out.mp4", "output_path": "other.mp4"}),
        ("duck_audio", {"video": "in.mp4", "music": "bed.wav", "music_path": "other.wav"}),
        ("duck_audio", {"video": "in.mp4", "music": "bed.wav", "output": "out.mp4", "output_path": "other.mp4"}),
    ],
)
def test_conflicting_audio_aliases_fail_before_engine_execution(method, kwargs, monkeypatch):
    target = "kinocut.engine_audio_mix.mix_audio" if method == "mix_audio" else "kinocut.engine_audio_ops.duck_audio"
    engine = Mock()
    monkeypatch.setattr(target, engine)
    with pytest.raises(MCPVideoError) as error:
        getattr(Client(), method)(**kwargs)
    assert error.value.code == "ambiguous_parameter"
    engine.assert_not_called()


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("mix_audio", {"video": "in.mp4", "tracks": [], "gain": 0.4}),
        ("duck_audio", {"video": "in.mp4", "music": "bed.wav", "gain": 0.4}),
    ],
)
def test_unknown_audio_parameters_return_structured_help(method, kwargs):
    with pytest.raises(MCPVideoError) as error:
        getattr(Client(), method)(**kwargs)
    assert error.value.code == "unexpected_parameter"
    assert f"Client.{method}()" in str(error.value)
    assert "Valid parameters" in str(error.value)
