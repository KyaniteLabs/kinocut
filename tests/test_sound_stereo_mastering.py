"""Actual stereo metering and retained masters preserve frames and channels."""

from array import array
import hashlib
import zipfile

import numpy as np
import pytest

from kinocut_sound._errors import SoundContractError
from kinocut_sound.delivery import DeliveryPolicy, DeliveryPreset, LoudnessTarget
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.public import master_job
from kinocut_sound.public.loudness_request import inspect_loudness
from kinocut_sound.qa import measure_loudness
from tests.test_sound_master_public import master_project, inspect_master  # noqa: F401


def write_stereo(root, request, kind="asymmetric"):
    rate = 48000
    t = np.arange(10 * rate) / rate
    left = 0.1 * np.sin(2 * np.pi * 1000 * t)
    right = 0.05 * np.sin(2 * np.pi * 500 * t)
    if kind == "left":
        right[:] = 0
    elif kind == "right":
        left[:] = 0
    elif kind == "antiphase":
        right = -left
    elif kind == "duplicate":
        right = left.copy()
    elif kind == "transient":
        left *= 0.3
        for pos in range(rate, len(left) - rate, rate):
            left[pos : pos + 8] = 0.9 * np.sin(2 * np.pi * 12000 * np.arange(8) / rate + np.pi / 4)
        right = left / 4
    pcm = np.column_stack((left, right))
    quantized = np.rint(pcm * 32767).astype(np.int16)
    if kind == "transient":
        # Keep the tested 4:1 relation exact before normalization amplifies PCM noise.
        quantized[:, 0] = np.rint(left * 32767 / 4).astype(np.int16) * 4
        quantized[:, 1] = quantized[:, 0] // 4
        assert not np.any(quantized[:, 0].astype(np.int32) - 4 * quantized[:, 1])
    data = pcm_to_wav(array("h", quantized.ravel()), sample_rate_hz=rate, channel_count=2)
    (root / "source.wav").write_bytes(data)
    request["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    return pcm, data


@pytest.fixture
def stereo_master_project(master_project):  # noqa: F811
    root, request = master_project
    write_stereo(root, request)
    return root, request


def retained_channels(root, result):
    receipt, metrics = inspect_master(root, result)
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        pcm, rate, channels = decode_pcm_wav(archive.read("master.wav"))
    assert channels == result["channel_count"] == receipt["channel_count"] == 2
    assert receipt["schema_version"] == result["schema_version"] == 2
    assert len(pcm) == 2 * receipt["frame_count"] == receipt["interleaved_sample_count"]
    assert receipt["frame_count"] == receipt["sample_count"] == result["frame_count"] == 10 * rate
    assert receipt["input_frame_count"] == receipt["input_sample_count"] == 480000
    assert receipt["input_interleaved_sample_count"] == 960000
    return np.asarray(pcm).reshape(-1, 2), receipt, metrics


@pytest.mark.parametrize("preset", list(DeliveryPreset))
@pytest.mark.parametrize("rate", [48000, 44100])
def test_stereo_master_hits_presets_and_resampled_frames(stereo_master_project, preset, rate):
    root, request = stereo_master_project
    target = LoudnessTarget.for_preset(preset)
    request["delivery"] = DeliveryPolicy(preset=preset, loudness=target).model_dump(mode="json")
    request["output_sample_rate_hz"] = rate
    pcm, _, (integrated, peak, _) = retained_channels(root, master_job.render_master_request(request, str(root)))
    assert abs(integrated - target.integrated_lufs) <= 0.2
    assert peak <= target.true_peak_dbtp
    t = np.arange(len(pcm)) / rate
    for channel, frequency in ((0, 1000), (1, 500)):
        assert np.corrcoef(pcm[:, channel], np.sin(2 * np.pi * frequency * t))[0, 1] > 0.99
    assert abs(np.corrcoef(pcm[:, 0], pcm[:, 1])[0, 1]) < 0.01


@pytest.mark.parametrize("kind", ["left", "right", "antiphase", "transient"])
def test_stereo_master_does_not_cancel_swap_or_unlink_channels(master_project, kind):  # noqa: F811
    root, request = master_project
    write_stereo(root, request, kind)
    pcm, _, _ = retained_channels(root, master_job.render_master_request(request, str(root)))
    if kind in ("left", "right"):
        active = 0 if kind == "left" else 1
        assert np.max(np.abs(pcm[:, active])) > 1000
        assert np.max(np.abs(pcm[:, 1 - active])) <= 1
    elif kind == "antiphase":
        assert np.max(np.abs(pcm.astype(np.int32).sum(axis=1))) <= 1
    else:
        assert np.max(np.abs(pcm[:, 0].astype(np.int32) - 4 * pcm[:, 1])) <= 8


def test_stereo_meter_counts_both_channels_without_downmix(master_project):  # noqa: F811
    root, request = master_project
    mono_i = measure_loudness((root / "source.wav").read_bytes())[0]
    _, duplicate = write_stereo(root, request, "duplicate")
    stereo_i = measure_loudness(duplicate)[0]
    assert stereo_i - mono_i == pytest.approx(3.0, abs=0.2)
    _, antiphase = write_stereo(root, request, "antiphase")
    report = inspect_loudness(antiphase)
    assert measure_loudness(antiphase)[0] == pytest.approx(stereo_i, abs=0.1)
    assert report["channel_count"] == 2 and report["frame_count"] == 480000
    assert report["interleaved_sample_count"] == 960000


def test_stereo_memory_budget_includes_output_channels(stereo_master_project, monkeypatch):
    root, request = stereo_master_project
    # Mono-sized output would fit; preserving both channels must reject this cap.
    monkeypatch.setattr(master_job, "MAX_MIX_INPUT_BYTES", 1200000)
    # Read admission has the same cap, so isolate output admission using verified bytes.
    source = (root / "source.wav").read_bytes()
    monkeypatch.setattr(master_job, "read_asset", lambda *args: source)
    with pytest.raises(SoundContractError) as failure:
        master_job.render_master_request(request, str(root))
    assert failure.value.code == "master_over_limit"
    assert not (root / "master.zip").exists()


def test_stereo_minimum_duration_uses_frames(stereo_master_project):
    root, _ = stereo_master_project
    samples, rate, channels = decode_pcm_wav((root / "source.wav").read_bytes())
    short = pcm_to_wav(samples[: 2 * rate * channels], sample_rate_hz=rate, channel_count=channels)
    with pytest.raises(SoundContractError) as failure:
        measure_loudness(short)
    assert failure.value.code == "qa_unmeasurable"


def test_stereo_mix_master_measure_chain(stereo_master_project):
    from kinocut import Client
    from kinocut_sound.timeline import Cue, CueKind, Timeline
    from tests.test_sound_public_mix import _minimal_plan

    root, request = stereo_master_project
    timeline = Timeline(
        cues=(Cue(cue_id="line", source_ref="source.wav", start_seconds=0, duration_seconds=10, kind=CueKind.LINE),),
        tail_seconds=0,
    )
    plan = _minimal_plan(timeline=timeline, lines=()).model_dump(mode="json")
    plan["format"].update(sample_rate_hz=48000, channel_layout="stereo")
    mix_request = {
        "plan": plan,
        "clips": [{**request["source"], "cue_id": "line", "stem_id": "dialogue"}],
        "output_path": "mix.zip",
    }
    mixed = Client().sound_mix_render(mix_request, str(root))
    with zipfile.ZipFile(root / mixed["output_path"]) as archive:
        data = archive.read("master.wav")
    (root / "mixed.wav").write_bytes(data)
    request["source"] = {"path": "mixed.wav", "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
    mastered = Client().sound_master_render(request, str(root))
    _, receipt, _ = retained_channels(root, mastered)
    with zipfile.ZipFile(root / mastered["output_path"]) as archive:
        final = archive.read("master.wav")
    report = Client().sound_qa_loudness(wav_bytes=final)
    assert report["within_tolerance"] is True
    assert report["channel_count"] == 2 and report["frame_count"] == receipt["frame_count"]
    assert report["source_sha256"] == receipt["media"]["master.wav"]["sha256"]


@pytest.mark.parametrize("kind", ["normal", "silent", "short"])
def test_asr_still_rejects_stereo_before_backend(stereo_master_project, monkeypatch, kind):
    from kinocut_sound.public import asr_job

    root, master_request = stereo_master_project
    if kind != "normal":
        samples, rate, channels = decode_pcm_wav((root / "source.wav").read_bytes())
        samples = array("h", [0]) * len(samples) if kind == "silent" else samples[: 2 * rate * channels]
        data = pcm_to_wav(samples, sample_rate_hz=rate, channel_count=channels)
        (root / "source.wav").write_bytes(data)
        master_request["source"]["sha256"] = "sha256:" + hashlib.sha256(data).hexdigest()
    (root / "reference.txt").write_text("hello")
    request = {
        "source": master_request["source"],
        "output_path": "asr.zip",
        "language": "en",
        "model": "base.en",
        "reference": {"path": "reference.txt", "sha256": "sha256:" + hashlib.sha256(b"hello").hexdigest()},
    }

    def unexpected_backend():
        pytest.fail("stereo ASR must fail before discovering a backend")

    monkeypatch.setattr(asr_job, "interpreters", unexpected_backend)
    with pytest.raises(SoundContractError) as failure:
        asr_job.recognize_sync(request, str(root))
    assert failure.value.code == "qa_input_invalid"
    assert not (root / "asr.zip").exists()


@pytest.mark.parametrize("kind", ["mono", "frames", "silent", "header"])
def test_stereo_hostile_output_cannot_publish(stereo_master_project, monkeypatch, kind):
    root, request = stereo_master_project
    original = master_job.run_sync

    def corrupt(args, deadline):
        output = original(args, deadline)
        if args[-1].endswith("master.wav"):
            from pathlib import Path

            path = Path(args[-1])
            pcm, rate, _ = decode_pcm_wav(path.read_bytes())
            channels = 2
            if kind == "mono":
                pcm, channels = pcm[::2], 1
            elif kind == "frames":
                pcm = pcm[:-2]
            elif kind == "silent":
                pcm = array("h", [0]) * len(pcm)
            data = pcm_to_wav(pcm, sample_rate_hz=rate, channel_count=channels)
            path.write_bytes(b"bad" if kind == "header" else data)
        return output

    monkeypatch.setattr(master_job, "run_sync", corrupt)
    with pytest.raises(SoundContractError):
        master_job.render_master_request(request, str(root))
    assert not (root / "master.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))
