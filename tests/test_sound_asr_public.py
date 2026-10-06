"""Actual installed cached recognition; no network or dependency installation."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import wave
import zipfile

import pytest

from kinocut import Client
from kinocut_sound.public import invoke_sound_operation
from kinocut_sound.public import asr_job
from kinocut_sound.public.asr_compare import compare
from kinocut_sound.public.asr_request import AsrError


PHRASES = {
    "en": "The train arrives at the station tomorrow morning. Please bring your ticket and a small bag.",
    "es": "El tren llega a la estación mañana por la mañana. Por favor trae tu billete y una bolsa pequeña.",
}


def asset(root, name):
    return {"path": name, "sha256": "sha256:" + hashlib.sha256((root / name).read_bytes()).hexdigest()}


@pytest.fixture
def asr_project(tmp_path):
    if not shutil.which("whisper") or not shutil.which("espeak-ng"):
        pytest.skip("installed local Whisper/eSpeak runtime unavailable")
    if not all((Path.home() / ".cache/whisper" / name).is_file() for name in ("base.en.pt", "base.pt")):
        pytest.skip("verified local model cache unavailable; downloads forbidden")

    def prepare(language="en", reference=None, trailing_silence=True):
        subprocess.run(
            ["espeak-ng", "-v", language, "-s", "145", "-w", str(tmp_path / "source.wav"), PHRASES[language]],
            check=True,
            capture_output=True,
            timeout=10,
        )
        if trailing_silence:
            # Preserve the spoken signal and include a real terminal pause.
            # Whisper pads its analysis window and can otherwise place its
            # final predicted timestamp beyond an abruptly ended source.
            with wave.open(str(tmp_path / "source.wav"), "rb") as source:
                params = source.getparams()
                frames = source.readframes(source.getnframes())
            with wave.open(str(tmp_path / "source.wav"), "wb") as output:
                output.setparams(params)
                output.writeframes(frames + bytes(params.framerate * params.sampwidth * params.nchannels))
        (tmp_path / "reference.txt").write_text(PHRASES[language] if reference is None else reference)
        return {
            "schema_version": 1,
            "source": asset(tmp_path, "source.wav"),
            "reference": asset(tmp_path, "reference.txt"),
            "language": language,
            "model": "base.en" if language == "en" else "base",
            "output_path": "recognized.zip",
        }

    return tmp_path, prepare


@pytest.mark.parametrize("language", ["en", "es"])
def test_actual_cached_recognition_retains_truth(asr_project, language):
    root, prepare = asr_project
    request = prepare(language)
    result = Client().sound_qa_asr(request=request, project_root=str(root))
    assert result["demo"] is False
    with zipfile.ZipFile(root / result["output_path"]) as archive:
        transcript = json.loads(archive.read("transcript.json"))
        receipt = json.loads(archive.read("receipt.json"))
    assert transcript["text"] and transcript["segments"]
    assert receipt["comparison"] == result["comparison"]
    assert result["ok"] == (result["comparison"]["word_error_rate"] == 0)
    if language == "en":
        assert result["ok"] is True
    # Spanish accuracy remains an observed result, never a fabricated match.
    assert result["backend"]["model_sha256"].startswith("sha256:")
    assert not list(root.glob(".kinocut-mix-*"))


def test_actual_unpadded_spanish_timestamps_follow_observed_boundary(asr_project, monkeypatch):
    root, prepare = asr_project
    request = prepare("es", trailing_silence=False)
    original = asr_job.validate_segments
    observed = {}

    def validate(payload, duration, rate):
        observed["duration"] = duration
        observed["within_bounds"] = all(
            type(value) in (int, float) and 0 <= value <= duration + 1 / rate
            for segment in payload["segments"]
            for value in (segment["start"], segment["end"])
        )
        return original(payload, duration, rate)

    monkeypatch.setattr(asr_job, "validate_segments", validate)
    try:
        result = Client().sound_qa_asr(request=request, project_root=str(root))
    except AsrError as failure:
        # Reject only a failure supported by the actual backend timestamps;
        # a different model/runtime may legitimately return bounded segments.
        assert observed.get("within_bounds") is False
        assert failure.code == "asr_invalid_output"
        assert "invalid ASR segment timestamp" in str(failure)
        assert not (root / request["output_path"]).exists()
    else:
        assert observed.get("within_bounds") is True
        assert result["demo"] is False
        with zipfile.ZipFile(root / result["output_path"]) as archive:
            transcript = json.loads(archive.read("transcript.json"))
            receipt = json.loads(archive.read("receipt.json"))
        assert all(
            0 <= segment["start"] <= segment["end"] <= observed["duration"] for segment in transcript["segments"]
        )
        assert receipt["comparison"] == result["comparison"] == compare(PHRASES["es"], transcript["text"])
    assert not list(root.glob(".kinocut-mix-*"))


def test_actual_mismatch_is_retained(asr_project):
    root, prepare = asr_project
    result = Client().sound_qa_asr(
        request=prepare(reference="These are entirely different words."), project_root=str(root)
    )
    assert result["ok"] is False
    assert result["verification_status"] == "recognized_mismatch"
    assert (root / "recognized.zip").is_file()


def test_legacy_simulated_port_is_removed():
    from kinocut_sound.public.asr_request import AsrError

    with pytest.raises(AsrError) as bare:
        invoke_sound_operation("sound-qa-asr")
    assert bare.value.code == "asr_input_invalid"

    with pytest.raises(AsrError):
        invoke_sound_operation(
            "sound-qa-asr",
            script_hashes=["sha256:" + "0" * 64],
            audio_duration_seconds=1.0,
        )


def test_real_request_rejects_legacy_hash_intent(asr_project):
    from kinocut_sound.public.asr_request import AsrError

    root, prepare = asr_project
    request = prepare()

    with pytest.raises(AsrError):
        invoke_sound_operation(
            "sound-qa-asr",
            request=request,
            project_root=str(root),
            script_hashes=["sha256:" + "0" * 64],
        )
