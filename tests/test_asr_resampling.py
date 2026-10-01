"""Actual bandlimited preprocessing without model downloads or recognition claims."""

import io
import shutil
import struct
from types import SimpleNamespace

import numpy as np
import pytest

from kinocut_sound.mix._wav import wav_from_pcm
from kinocut_sound.public import asr_resample
from kinocut_sound.public.asr_input import validate_header
from kinocut_sound.public.asr_request import AsrError
from kinocut_sound.qa._errors import QaError, QA_INPUT_INVALID
from kinocut_sound.qa.meter_process import run_meter_sync
from kinocut_sound.limits import MAX_ASR_INPUT_BYTES, MAX_ASR_METADATA_BYTES


@pytest.fixture
def ffmpeg():
    if not shutil.which("ffmpeg"):
        pytest.skip("installed FFmpeg required")
    return asr_resample.installed_resampler()


def preprocess(tmp_path, binary, rate, samples):
    (tmp_path / "source.pcm").write_bytes(samples.astype("<i2").tobytes())
    job = SimpleNamespace(root=tmp_path, rate=rate, duration=len(samples) / rate)
    run_meter_sync(asr_resample.command(binary, job), 10)
    return np.fromfile(tmp_path / "source.f32", dtype="<f4")


def test_actual_downsample_suppresses_out_of_band_alias_and_preserves_passband(tmp_path, ffmpeg):
    rate = 48000
    time = np.arange(rate, dtype=np.float64) / rate
    signal = np.rint(12000 * np.sin(2 * np.pi * 1000 * time) + 12000 * np.sin(2 * np.pi * 11000 * time))
    output = preprocess(tmp_path, ffmpeg, rate, signal)
    assert len(output) == 16000
    # Exclude FIR edge padding, measure exact integer-frequency projections.
    middle = output[1600:-1600]
    target_time = np.arange(len(middle)) / 16000

    def amplitude(freq):
        return abs(2 * np.mean(middle * np.exp(-2j * np.pi * freq * target_time)))

    assert amplitude(1000) == pytest.approx(12000 / 32768, rel=0.01)
    assert amplitude(5000) < 0.0001  # former 11 kHz -> 5 kHz alias was ~0.14
    assert np.isfinite(output).all()


@pytest.mark.parametrize("rate", [8000, 22050, 24000, 44100, 48000])
@pytest.mark.parametrize("frames", [1, 2, 17, 101])
def test_short_noninteger_ratio_output_has_exact_declared_frame_count(tmp_path, ffmpeg, rate, frames):
    output = preprocess(tmp_path, ffmpeg, rate, np.full(frames, 1234))
    assert len(output) == round(frames / rate * 16000)
    assert np.isfinite(output).all()


@pytest.mark.parametrize("raw", [b"", b"\xff", b"ffmpeg version /private/path\n", b"other version 1.0\n"])
def test_invalid_backend_identity_fails_without_exposing_paths(raw):
    with pytest.raises(AsrError) as failure:
        asr_resample.backend_version(raw)
    assert failure.value.code == "asr_unavailable"
    assert "private" not in str(failure.value)


def test_actual_backend_version_is_safe_receipt_identity(ffmpeg):
    version = asr_resample.backend_version(run_meter_sync([ffmpeg, "-version"], 10))
    assert version and "/" not in version


class HeaderOnlyReader(io.BytesIO):
    def read(self, size=-1):
        assert 0 <= size <= 16, "preflight attempted to allocate PCM or a large metadata chunk"
        return super().read(size)


@pytest.mark.parametrize("rate,frames", [(48000, 48000 * 120 + 1), (96000, 3 * 96000)])
def test_header_declared_duration_rate_rejected_without_pcm_read(rate, frames):
    data = wav_from_pcm(b"\0\0" * frames, sample_rate_hz=rate)
    with pytest.raises(AsrError) as failure:
        validate_header(HeaderOnlyReader(data), len(data))
    assert failure.value.code == "asr_over_limit"


def test_max_duration_and_odd_unknown_chunk_accepted_with_header_only_scan():
    data = wav_from_pcm(b"\0\0" * (48000 * 120), sample_rate_hz=48000)
    padded = data[:12] + b"JUNK" + struct.pack("<I", 3) + b"abc\0" + data[12:]
    padded = padded[:4] + struct.pack("<I", len(padded) - 8) + padded[8:]
    validate_header(HeaderOnlyReader(padded), len(padded))
    assert len(padded) < MAX_ASR_INPUT_BYTES


def test_metadata_allowance_rejects_padding_before_reading_it():
    data = wav_from_pcm(b"\0\0" * 48000, sample_rate_hz=16000)
    padded = data[:12] + b"JUNK" + struct.pack("<I", MAX_ASR_METADATA_BYTES) + bytes(MAX_ASR_METADATA_BYTES) + data[12:]
    padded = padded[:4] + struct.pack("<I", len(padded) - 8) + padded[8:]
    with pytest.raises(AsrError, match="metadata exceeds"):
        validate_header(HeaderOnlyReader(padded), len(padded))


@pytest.mark.parametrize(
    "kind", ["duplicate", "unaligned", "truncated", "wrong_width", "missing_fmt", "bad_magic", "wrong_riff_length"]
)
def test_hostile_header_rejected_before_pcm_read(kind):
    data = wav_from_pcm(b"\0\0" * 48000, sample_rate_hz=16000)
    if kind == "duplicate":
        data = data + b"data\0\0\0\0"
        data = data[:4] + struct.pack("<I", len(data) - 8) + data[8:]
    elif kind == "unaligned":
        data = data[:-1] + b"\0\0"
        data = data[:4] + struct.pack("<I", len(data) - 8) + data[8:40] + struct.pack("<I", 96001) + data[44:]
    elif kind == "truncated":
        data = data[:-1]
    elif kind == "wrong_width":
        data = data[:34] + struct.pack("<H", 32) + data[36:]
    elif kind == "bad_magic":
        data = b"invalid!" + data[8:]
    elif kind == "wrong_riff_length":
        data = data[:4] + struct.pack("<I", len(data) - 9) + data[8:]
    else:
        data = data[:12] + b"JUNK" + data[16:]
    with pytest.raises(QaError) as failure:
        validate_header(HeaderOnlyReader(data), len(data))
    assert failure.value.code == QA_INPUT_INVALID
