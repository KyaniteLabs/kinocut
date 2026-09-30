"""Output equivalence and bounded repeated-work regressions."""

from __future__ import annotations

import io
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import wave
import weakref

import numpy as np
from PIL import Image
import pytest

from kinocut.ai_engine import _longform_runtime as runtime
from kinocut.ai_engine import transcribe_longform as longform
from kinocut.ai_engine._longform_models import LongformChunk, LongformTranscribePlan
from kinocut.aesthetic import smart_thumbnail
from kinocut.ai_engine.upscale import _verify_model_hash
from kinocut.errors import MCPVideoError
from kinocut_sound.voice_consistency import distinctiveness as voice
from kinocut_sound.voice_consistency._errors import VoiceConsistencyError


def _wav(values: tuple[int, ...], rate: int = 16_000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(values)}h", *values))
    return buffer.getvalue()


def test_roster_distances_equal_pairwise_reference_without_repeated_features(monkeypatch):
    pairs = tuple((str(i), _wav(tuple((j * (i + 1) * 999) % 20000 - 10000 for j in range(128)))) for i in range(5))
    expected = tuple(voice.spectral_distance(a[1], b[1]) for i, a in enumerate(pairs) for b in pairs[i + 1 :])
    calls = []
    original = voice._features

    def measured(samples, rate):
        calls.append(rate)
        return original(samples, rate)

    monkeypatch.setattr(voice, "_features", measured)
    report = voice.detect_collisions(pairs)
    assert report.distances == expected
    assert len(calls) == len(pairs)
    assert report.collisions == tuple(
        pair for pair, distance in zip(report.pairs, expected, strict=True) if distance < 0.05
    )


def test_roster_still_rejects_mismatched_rates():
    with pytest.raises(VoiceConsistencyError, match="matching sample rates"):
        voice.detect_collisions((("a", _wav((1, 2))), ("b", _wav((1, 2), 8000))))


def test_longform_loads_model_once_per_job_and_releases_between_jobs(monkeypatch, tmp_path):
    loads, options, models = [], [], []

    class Model:
        def transcribe(self, path, **kwargs):
            assert Path(path).is_file()
            options.append(kwargs)
            return {"text": "hello", "language": "en", "segments": []}

    def load(name):
        loads.append(name)
        model = Model()
        models.append(weakref.ref(model))
        return model

    def extract(*args, **kwargs):
        path = Path(kwargs["output_dir"]) / "chunk.wav"
        path.write_bytes(b"wav")
        return str(path)

    plan = LongformTranscribePlan(
        video_path="source.mp4",
        duration=60,
        chunk_seconds=40,
        overlap_seconds=5,
        chunks=(
            LongformChunk(index=0, start=0, end=40, duration=40),
            LongformChunk(index=1, start=35, end=60, duration=25),
        ),
    )
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(load_model=load))
    monkeypatch.setattr(runtime, "_extract_audio_segment", extract)
    monkeypatch.setattr(longform, "_validate_longform_path", lambda path: path)
    monkeypatch.setattr(longform, "_get_video_duration", lambda path: 60)
    for _ in range(2):
        result = longform.transcribe_longform("source.mp4", model="base", language="en", plan=plan)
        assert result.chunk_count == 2
    assert loads == ["base", "base"]
    assert all(model() is None for model in models)
    assert len(options) == 4
    assert all(option == {"word_timestamps": True, "task": "transcribe", "language": "en"} for option in options)


@pytest.mark.parametrize("fail", [False, True])
def test_thumbnail_candidates_live_during_scoring_and_clean_up_afterwards(monkeypatch, sample_video, fail):
    from kinocut import aesthetic

    seen = []

    class Scorer:
        def score_frames(self, paths):
            seen.extend(paths)
            for path in paths:
                with Image.open(path) as image:
                    assert image.width > 0
            if fail:
                raise RuntimeError("scoring failed")
            return [1.0, 5.0, 2.0]

    monkeypatch.setattr(aesthetic, "is_available", lambda: True)
    monkeypatch.setattr(aesthetic.NimaScorer, "get", lambda: Scorer())
    monkeypatch.setattr(smart_thumbnail, "_get_video_duration", lambda path: 3.0)
    # Keep this focused on file lifetime; the minimum duration is checked elsewhere.
    monkeypatch.setattr(smart_thumbnail, "DEFAULT_NIMA_MIN_DURATION", 0)
    if fail:
        with pytest.raises(RuntimeError, match="scoring failed"):
            smart_thumbnail._select_best_with_nima(sample_video, 3)
    else:
        assert smart_thumbnail._select_best_with_nima(sample_video, 3) == pytest.approx(1.5)
    assert len(seen) == 3
    assert all(not Path(path).exists() for path in seen)
    assert not Path(seen[0]).parent.exists()


def test_equal_color_counts_keep_first_observed_cluster_order(monkeypatch, tmp_path):
    from sklearn import cluster
    from kinocut.image_engine import extract_colors

    class Model:
        cluster_centers_ = np.array([[255, 0, 0], [0, 0, 255]])

        def fit_predict(self, pixels):
            return np.array([1, 0, 1, 0])

    image = tmp_path / "colors.png"
    Image.new("RGB", (2, 2)).save(image)
    monkeypatch.setattr(cluster, "MiniBatchKMeans", lambda **kwargs: Model())
    colors = extract_colors(str(image), n_colors=2).colors
    assert [c.rgb for c in colors] == [(0, 0, 255), (255, 0, 0)]
    assert [c.percentage for c in colors] == [50.0, 50.0]


def test_streamed_model_hash_preserves_integrity_failure_and_deletion(tmp_path):
    import hashlib

    path = tmp_path / "model.pb"
    payload = b"verified model" * 100_000
    path.write_bytes(payload)
    _verify_model_hash(path, hashlib.sha256(payload).hexdigest())
    assert path.is_file()
    with pytest.raises(MCPVideoError) as exc:
        _verify_model_hash(path, "0" * 64)
    assert exc.value.code == "model_hash_mismatch"
    assert not path.exists()


@pytest.mark.parametrize(
    "rate,expected_pitch",
    [(8000, 0.8966466657044962), (16000, 0.9279629517651544), (48000, 0.9091951667307949)],
)
def test_bounded_pitch_window_preserves_baseline_features(rate, expected_pitch):
    # Values recorded from the pre-optimization function at a820bd4.
    values = tuple((i * 1871) % 40000 - 20000 for i in range(10240))
    samples, parsed_rate = voice._parse_wav(_wav(values, rate))
    assert samples == values
    assert parsed_rate == rate
    assert voice._features(samples, rate) == pytest.approx(
        (0.3523738906244104, 0.09345703125, 0.05437740188451097, expected_pitch),
        abs=1e-12,
    )
