"""Retained two-pass mastering requires measured final audio and safe publication."""

import hashlib
import json
import shutil
import zipfile

import numpy as np
import pytest

from kinocut_sound.delivery import DeliveryPolicy, DeliveryPreset, LoudnessTarget
from kinocut_sound._errors import SoundContractError
from kinocut_sound.public.mix_files import require_safe_filesystem
from kinocut_sound.post._fixtures import write_wav
from kinocut_sound.public.master_job import render_master_request
from kinocut_sound.public.master_request import MasterError, load_master_request
from kinocut_sound.qa import measure_loudness


@pytest.fixture
def master_project(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("requires installed FFmpeg")
    try:
        require_safe_filesystem()
    except SoundContractError:
        pytest.skip("descriptor-relative mastering files unavailable")
    rate = 48000
    time = np.arange(10 * rate) / rate
    path = write_wav(tmp_path / "source.wav", 0.1 * np.sin(2 * np.pi * 1000 * time), rate)
    request = {
        "source": {"path": path.name, "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()},
        "output_path": "master.zip",
    }
    return tmp_path, request


def inspect_master(root, result):
    archive_path = root / result["output_path"]
    assert "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest() == result["output_sha256"]
    with zipfile.ZipFile(archive_path) as archive:
        assert sorted(archive.namelist()) == ["master.wav", "receipt.json"]
        receipt = json.loads(archive.read("receipt.json"))
        data = archive.read("master.wav")
    assert receipt["media"]["master.wav"] == {
        "bytes": len(data),
        "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
    }
    assert receipt["source_sha256"] == result["source_sha256"]
    assert receipt["measurement"]["within_tolerance"] is True
    assert receipt["normalization_type"] in {"linear", "dynamic"}
    assert receipt["timing_proof"] == "frame_count_only"
    assert not list(root.glob(".kinocut-mix-*"))
    return receipt, measure_loudness(data)


@pytest.mark.parametrize("preset", list(DeliveryPreset))
@pytest.mark.parametrize("output_rate", [48000, 44100])
def test_retained_master_hits_all_presets(master_project, preset, output_rate):
    root, request = master_project
    target = LoudnessTarget.for_preset(preset)
    request["delivery"] = DeliveryPolicy(preset=preset, loudness=target).model_dump(mode="json")
    request["output_sample_rate_hz"] = output_rate
    receipt, (integrated, peak, _) = inspect_master(root, render_master_request(request, str(root)))
    assert abs(integrated - target.integrated_lufs) <= 0.2
    assert peak <= target.true_peak_dbtp
    assert receipt["sample_count"] == 10 * output_rate


@pytest.mark.parametrize("output_rate", [48000, 44100])
def test_transient_case_meets_target_after_two_passes(master_project, output_rate):
    root, request = master_project
    rate = 48000
    time = np.arange(10 * rate) / rate
    samples = 0.03 * np.sin(2 * np.pi * 1000 * time)
    for pos in range(rate, len(samples) - rate, rate):
        samples[pos : pos + 8] = 0.9 * np.sin(2 * np.pi * 12000 * np.arange(8) / rate + np.pi / 4)
    path = write_wav(root / "source.wav", samples, rate)
    request["source"]["sha256"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    request["output_sample_rate_hz"] = output_rate
    receipt, (integrated, peak, _) = inspect_master(root, render_master_request(request, str(root)))
    assert integrated == pytest.approx(-14, abs=0.2)
    assert peak <= -1
    assert receipt["normalization_type"] == "dynamic"
    assert receipt["internal_peak_target_dbtp"] == -1.2


def test_unmet_targets_never_publish(master_project):
    root, request = master_project
    request["delivery"] = DeliveryPolicy(loudness=LoudnessTarget(integrated_lufs=-5, true_peak_dbtp=-9)).model_dump(
        mode="json"
    )
    with pytest.raises(MasterError) as failure:
        render_master_request(request, str(root))
    assert failure.value.code == "master_target_unmet"
    assert not (root / "master.zip").exists()
    assert not list(root.glob(".kinocut-mix-*"))


@pytest.mark.parametrize("root", [None, "", "   "])
def test_missing_explicit_root_rejected(master_project, root):
    _, request = master_project
    with pytest.raises(MasterError):
        load_master_request(request, root)


@pytest.mark.parametrize(
    "changes",
    [
        {"stems": {"stem_ids": ["dialogue"]}},
        {"metadata_codes": ["tag"]},
        {"master_only_limiting_enabled": True},
        {"recombination": {"comparison_reference": "post_master"}},
    ],
)
def test_unsupported_policy_intent_rejected(master_project, changes):
    root, request = master_project
    request["delivery"] = changes
    with pytest.raises(MasterError) as failure:
        render_master_request(request, str(root))
    assert failure.value.code == "master_unsupported_intent"
    assert not (root / "master.zip").exists()


def test_existing_output_preserved(master_project):
    root, request = master_project
    output = root / "master.zip"
    output.write_bytes(b"owner content")
    with pytest.raises(MasterError) as failure:
        render_master_request(request, str(root))
    assert failure.value.code == "master_output_conflict"
    assert output.read_bytes() == b"owner content"
