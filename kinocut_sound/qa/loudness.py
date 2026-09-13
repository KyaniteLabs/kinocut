"""Loudness / true-peak / LRA compliance gates."""

from __future__ import annotations
from dataclasses import dataclass
from kinocut_sound.delivery import DeliveryPolicy
from kinocut_sound.qa._errors import QA_LOUDNESS_FAIL, qa_error
from kinocut_sound.qa.meter import measure_with_identity


@dataclass(frozen=True)
class LoudnessReport:
    integrated_lufs: float
    true_peak_dbtp: float
    lra_lu: float
    within_tolerance: bool
    preset: str


def measure_loudness(wav_bytes: bytes) -> tuple[float, float, float]:
    return measure_with_identity(wav_bytes)[0]


def evaluate_loudness(metrics, delivery: DeliveryPolicy | None = None) -> LoudnessReport:
    delivery = delivery or DeliveryPolicy()
    lufs, tp, lra = metrics
    ceiling = min(delivery.loudness.true_peak_dbtp, delivery.true_peak_ceiling_dbtp)
    within = abs(lufs - delivery.loudness.integrated_lufs) <= delivery.loudness.tolerance_lu and tp <= ceiling
    return LoudnessReport(
        integrated_lufs=lufs,
        true_peak_dbtp=tp,
        lra_lu=lra,
        within_tolerance=within,
        preset=str(getattr(delivery.preset, "value", delivery.preset)),
    )


def check_loudness(wav_bytes: bytes, delivery: DeliveryPolicy | None = None) -> LoudnessReport:
    report = evaluate_loudness(measure_loudness(wav_bytes), delivery)
    if not report.within_tolerance:
        raise qa_error("loudness outside delivery tolerance", QA_LOUDNESS_FAIL)
    return report
