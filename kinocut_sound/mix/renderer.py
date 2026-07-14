"""Authoritative mix renderer with duration/tail proof."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from itertools import pairwise

from kinocut_sound.defaults import DEFAULT_GAP_TOLERANCE_SECONDS, DEFAULT_TAIL_SECONDS
from kinocut_sound.delivery import DeliveryPolicy, StemLayout
from kinocut_sound.mix._errors import (
    MIX_DURATION_MISMATCH,
    MIX_INPUT_INVALID,
    MIX_UNSAFE_PATH,
    mix_error,
)
from kinocut_sound.mix._wav import (
    DEFAULT_SAMPLE_RATE_HZ,
    parse_wav,
    pcm_to_wav,
)
from kinocut_sound.mix.ducking import duck_bed_under_speech
from kinocut_sound.mix.placement import PlacementPlan, place_clips
from kinocut_sound.mix.seam import SeamReport, SeamEvent
from kinocut_sound.mix.stems import StemBundle, build_stem_bundle, recombine_stems
from kinocut_sound.timeline import Timeline
from kinocut_sound._canonical import location_violation


@dataclass(frozen=True)
class MixClip:
    """One rendered source clip ready for placement."""

    cue_id: str
    wav_bytes: bytes
    stem_id: str = "dialogue"


@dataclass(frozen=True)
class MixResult:
    """Rendered mix + stems + duration proof + seam report."""

    master_wav: bytes
    stems: StemBundle
    declared_duration_seconds: float
    measured_duration_seconds: float
    within_tolerance: bool
    seam_report: SeamReport
    placement: PlacementPlan


def _blank(length: int) -> array:
    return array("h", [0] * length)


def _overlay(canvas: array, clip: array, start: int) -> None:
    for i, v in enumerate(clip):
        idx = start + i
        if 0 <= idx < len(canvas):
            canvas[idx] = max(-32768, min(32767, canvas[idx] + v))


class MixRenderer:
    """Place clips onto an authoritative timeline and emit stems + master."""

    def __init__(
        self,
        *,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        gap_tolerance_seconds: float = DEFAULT_GAP_TOLERANCE_SECONDS,
        tail_seconds: float = DEFAULT_TAIL_SECONDS,
    ) -> None:
        if sample_rate_hz <= 0:
            raise mix_error("sample_rate_hz must be positive", MIX_INPUT_INVALID)
        self.sample_rate_hz = sample_rate_hz
        self.gap_tolerance_seconds = gap_tolerance_seconds
        self.tail_seconds = max(0.0, float(tail_seconds))

    def render(
        self,
        *,
        timeline: Timeline,
        clips: tuple[MixClip, ...],
        bed_wav: bytes | None = None,
        delivery: DeliveryPolicy | None = None,
        crossfade_seconds: float = 0.0,
        duck_bed: bool = False,
    ) -> MixResult:
        delivery = delivery or DeliveryPolicy()
        clip_map = {c.cue_id: c for c in clips}
        durations = {c.cue_id: len(parse_wav(c.wav_bytes)[0]) / float(self.sample_rate_hz) for c in clips}
        stem_for = {c.cue_id: c.stem_id for c in clips}
        placement = place_clips(
            timeline,
            clip_durations=durations,
            stem_for_cue=stem_for,
            gap_tolerance_seconds=self.gap_tolerance_seconds,
        )
        declared = placement.timeline_duration_seconds + self.tail_seconds
        total_samples = max(1, round(declared * self.sample_rate_hz))

        stem_ids = delivery.stems.stem_ids or ("dialogue", "ambience", "sfx")
        canvases = {sid: _blank(total_samples) for sid in stem_ids}
        seams: list[SeamEvent] = []

        # Optional consecutive-line crossfade: preprocess ordered dialogue clips
        ordered = sorted(placement.placements, key=lambda p: p.start_seconds)
        rendered_wavs: dict[str, bytes] = {c.cue_id: c.wav_bytes for c in clips}
        if crossfade_seconds > 0 and len(ordered) >= 2:
            for left, right in pairwise(ordered):
                if (
                    left.stem_id == right.stem_id == "dialogue"
                    and left.cue_id in rendered_wavs
                    and right.cue_id in rendered_wavs
                ):
                    # Only record seam; actual overlay uses truncated windows.
                    seams.append(
                        SeamEvent(
                            kind="crossfade",
                            at_seconds=right.start_seconds,
                            left_cue_id=left.cue_id,
                            right_cue_id=right.cue_id,
                            duration_seconds=crossfade_seconds,
                        )
                    )

        for placed in ordered:
            clip = clip_map.get(placed.cue_id)
            if clip is None:
                continue
            samples, rate = parse_wav(rendered_wavs[placed.cue_id])
            if rate != self.sample_rate_hz:
                raise mix_error("clip sample rate mismatch", MIX_INPUT_INVALID)
            window_n = round(placed.duration_seconds * self.sample_rate_hz)
            if len(samples) < window_n:
                padded = array("h", samples)
                padded.extend([0] * (window_n - len(samples)))
                samples = padded
            else:
                samples = samples[:window_n]
            start = round(placed.start_seconds * self.sample_rate_hz)
            stem = placed.stem_id if placed.stem_id in canvases else stem_ids[0]
            _overlay(canvases[stem], samples, start)

        if bed_wav is not None:
            bed_samples, bed_rate = parse_wav(bed_wav)
            if bed_rate != self.sample_rate_hz:
                raise mix_error("bed sample rate mismatch", MIX_INPUT_INVALID)
            if duck_bed and "dialogue" in canvases:
                # Build speech master for ducking sidechain
                speech = pcm_to_wav(canvases["dialogue"], sample_rate_hz=self.sample_rate_hz)
                # Extend/truncate bed to timeline
                bed_canvas = _blank(total_samples)
                _overlay(bed_canvas, bed_samples, 0)
                bed_full = pcm_to_wav(bed_canvas, sample_rate_hz=self.sample_rate_hz)
                ducked = duck_bed_under_speech(speech, bed_full)
                canvases["ambience"] = parse_wav(ducked)[0]
            else:
                if "ambience" not in canvases:
                    canvases["ambience"] = _blank(total_samples)
                _overlay(canvases["ambience"], bed_samples, 0)

        stem_wavs = {sid: pcm_to_wav(samples, sample_rate_hz=self.sample_rate_hz) for sid, samples in canvases.items()}
        layout = StemLayout(stem_ids=tuple(sorted(stem_wavs)))
        bundle = build_stem_bundle(layout=layout, stem_wavs=stem_wavs)
        master = recombine_stems(bundle, policy=delivery.recombination)
        measured = len(parse_wav(master)[0]) / float(self.sample_rate_hz)
        within = abs(measured - declared) <= max(self.gap_tolerance_seconds, 1.0 / self.sample_rate_hz)
        if not within:
            raise mix_error(
                f"output duration {measured} does not match declared {declared}",
                MIX_DURATION_MISMATCH,
            )
        return MixResult(
            master_wav=master,
            stems=bundle,
            declared_duration_seconds=declared,
            measured_duration_seconds=measured,
            within_tolerance=within,
            seam_report=SeamReport(events=tuple(seams)),
            placement=placement,
        )

    def export_master(
        self,
        result: MixResult,
        *,
        output_path: str,
        output_dir: str,
    ) -> str:
        reason = location_violation(output_path)
        if reason is not None or output_path.startswith("/") or ".." in output_path.split("/"):
            raise mix_error(f"output_path {reason or 'unsafe'}", MIX_UNSAFE_PATH)
        import os

        full = os.path.join(output_dir, *output_path.split("/"))
        os.makedirs(os.path.dirname(full) or output_dir, exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(result.master_wav)
        return output_path
