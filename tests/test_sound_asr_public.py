"""Actual installed cached recognition; no network or dependency installation."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from kinocut import Client
from kinocut_sound.public import invoke_sound_operation


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

    def prepare(language="en", reference=None):
        subprocess.run(
            ["espeak-ng", "-v", language, "-s", "145", "-w", str(tmp_path / "source.wav"), PHRASES[language]],
            check=True,
            capture_output=True,
            timeout=10,
        )
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


def test_actual_mismatch_is_retained(asr_project):
    root, prepare = asr_project
    result = Client().sound_qa_asr(
        request=prepare(reference="These are entirely different words."), project_root=str(root)
    )
    assert result["ok"] is False
    assert result["verification_status"] == "recognized_mismatch"
    assert (root / "recognized.zip").is_file()


def test_legacy_is_explicitly_simulated():
    result = invoke_sound_operation("sound-qa-asr")
    assert result["demo"] is True
    assert result["verification_status"] == "simulated"
