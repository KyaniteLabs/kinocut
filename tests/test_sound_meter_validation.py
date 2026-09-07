"""No invented measurements from missing, invalid or nonfinal meter evidence."""

import pytest

from kinocut_sound.qa import QaError
from kinocut_sound.qa import meter
from tests.test_sound_measured_loudness import calibration_wave  # noqa: F401 - pytest fixture


SUMMARY = b"""Summary:
Integrated loudness:
 I: -23.0 LUFS
 Threshold: -33.0 LUFS
Loudness range:
 LRA: 0.0 LU
 Threshold: -43.0 LUFS
 LRA low: -23.0 LUFS
 LRA high: -23.0 LUFS
True peak:
 Peak: -20.0 dBFS
"""


@pytest.mark.parametrize(
    "output",
    [
        b"SUCCESS",
        SUMMARY + b"Summary: broken",
        SUMMARY.replace(b"True peak:", b"sample peak:"),
        SUMMARY.replace(b"-23.0", b"NaN"),
        SUMMARY.replace(b"-20.0", b"inf"),
        SUMMARY.replace(b"LRA: 0.0", b"LRA: -1"),
        SUMMARY.replace(b"I: -23.0", b"I: -70.0"),
    ],
)
def test_invalid_or_nonfinal_summaries_fail(output):
    with pytest.raises(QaError):
        meter.parse_summary(output)


def test_only_final_complete_summary_counts():
    assert meter.parse_summary(b"Summary: partial\n" + SUMMARY) == (-23.0, -20.0, 0.0)


def test_unavailable_engine_has_no_proxy_fallback(monkeypatch, calibration_wave):  # noqa: F811 - fixture injection
    monkeypatch.setattr(meter.shutil, "which", lambda _: None)
    with pytest.raises(QaError) as failure:
        meter.measure_with_identity(calibration_wave)
    assert failure.value.code == "qa_unavailable"


def test_input_cap_precedes_decode(monkeypatch):
    monkeypatch.setattr(meter, "MAX_MIX_INPUT_BYTES", 4)

    def decode(_):
        pytest.fail("oversized input decoded")

    monkeypatch.setattr(meter, "parse_wav", decode)
    with pytest.raises(QaError):
        meter.validate_material(b"12345")


@pytest.mark.parametrize("output", [b"SUCCESS", b"ffmpeg version /host/private", b"ffmpeg version " + b"x" * 81])
def test_invalid_version_is_bounded(output):
    with pytest.raises(QaError):
        meter._version(output)
