"""Authoritative mix renderer with duration/tail proof."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from math import isfinite

from kinocut_sound.defaults import DEFAULT_GAP_TOLERANCE_SECONDS, DEFAULT_TAIL_SECONDS, DEFAULT_MIX_CHANNEL_COUNT
from kinocut_sound.validation import PCM_MIX_CHANNEL_COUNTS
from kinocut_sound.delivery import DeliveryPolicy, StemLayout
from kinocut_sound.mix._errors import (
    MIX_DURATION_MISMATCH,
    MIX_INPUT_INVALID,
    MIX_CROSSFADE_INVALID,
    MIX_UNSAFE_PATH,
    mix_error,
)
from kinocut_sound.mix._wav import (
    DEFAULT_SAMPLE_RATE_HZ,
    decode_pcm_wav,
    pcm_to_wav,
)
from kinocut_sound.mix.ducking import duck_bed_under_speech
from kinocut_sound.mix.placement import PlacedClip, PlacementPlan, place_clips
from kinocut_sound.mix.seam import SeamReport
from kinocut_sound.mix.source_windows import SourceWindow, select_source_windows
from kinocut_sound.mix.transitions import CrossfadeTransition, apply_transitions
from kinocut_sound.mix.stems import StemBundle, build_stem_bundle, recombine_stems
from kinocut_sound.mix.routing_protocol import RoutingProcessor
from kinocut_sound.mix.layers import MixLayer, apply_layers
from kinocut_sound.mix.pcm_ops import _overlay
from kinocut_sound.timeline import Timeline
from kinocut_sound.world.layers import DuckingContract
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
    source_windows: tuple[SourceWindow, ...] = ()
    layer_source_frames: tuple[int, ...] = ()
    layer_ducking_summary: dict | None = None
    bus_sidechain_measurements: tuple[dict, ...] = ()


def _blank(length: int) -> array:
    return array("h", [0] * length)


class MixRenderer:
    """Place clips onto an authoritative timeline and emit stems + master.

    Declare output padding on ``Timeline.tail_seconds``. A nonzero legacy
    renderer ``tail_seconds`` must match that declaration; it is not additive.
    """

    def __init__(
        self,
        *,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
        gap_tolerance_seconds: float = DEFAULT_GAP_TOLERANCE_SECONDS,
        tail_seconds: float = DEFAULT_TAIL_SECONDS,
        channel_count: int = DEFAULT_MIX_CHANNEL_COUNT,
    ) -> None:
        if sample_rate_hz <= 0:
            raise mix_error("sample_rate_hz must be positive", MIX_INPUT_INVALID)
        self.sample_rate_hz = sample_rate_hz
        if type(channel_count) is not int or channel_count not in PCM_MIX_CHANNEL_COUNTS:
            raise mix_error("mix channel count must be mono or stereo", MIX_INPUT_INVALID)
        self.channel_count = channel_count
        self.gap_tolerance_seconds = gap_tolerance_seconds
        try:
            self.tail_seconds = float(tail_seconds)
        except (TypeError, ValueError, OverflowError) as exc:
            raise mix_error("tail_seconds must be finite and nonnegative", MIX_INPUT_INVALID) from exc
        if isinstance(tail_seconds, bool) or not isfinite(self.tail_seconds) or self.tail_seconds < 0:
            raise mix_error("tail_seconds must be finite and nonnegative", MIX_INPUT_INVALID)

    def render(
        self,
        *,
        timeline: Timeline,
        clips: tuple[MixClip, ...],
        bed_wav: bytes | None = None,
        delivery: DeliveryPolicy | None = None,
        crossfade_seconds: float = 0.0,
        duck_bed: bool = False,
        transitions: tuple[CrossfadeTransition, ...] = (),
        routing: RoutingProcessor | None = None,
        layers: tuple[MixLayer, ...] = (),
        layer_ducking: DuckingContract | None = None,
    ) -> MixResult:
        if isinstance(crossfade_seconds, bool) or crossfade_seconds != 0:
            raise mix_error(
                "use explicit CrossfadeTransition entries instead of crossfade_seconds", MIX_CROSSFADE_INVALID
            )
        delivery = delivery or DeliveryPolicy()
        clip_map = {c.cue_id: c for c in clips}
        if transitions and len(clip_map) != len(clips):
            raise mix_error("transition sources must have unique cue ids", MIX_CROSSFADE_INVALID)
        selected, windows = select_source_windows(
            timeline, {c.cue_id: c.wav_bytes for c in clips}, self.sample_rate_hz, self.channel_count
        )
        if routing is not None:
            selected = routing.process_sources(selected, self.sample_rate_hz)
        clips = tuple(MixClip(c.cue_id, selected[c.cue_id], c.stem_id) for c in clips)
        clip_map = {c.cue_id: c for c in clips}
        durations = {
            c.cue_id: len(self._decode(c.wav_bytes)) / float(self.sample_rate_hz * self.channel_count) for c in clips
        }
        stem_for = {c.cue_id: c.stem_id for c in clips}
        placement = place_clips(
            timeline,
            clip_durations=durations,
            stem_for_cue=stem_for,
            gap_tolerance_seconds=self.gap_tolerance_seconds,
        )
        if self.tail_seconds and self.tail_seconds != timeline.tail_seconds:
            raise mix_error("renderer tail must match Timeline.tail_seconds", MIX_DURATION_MISMATCH)
        declared = placement.timeline_duration_seconds
        total_samples = max(1, round(declared * self.sample_rate_hz)) * self.channel_count

        stem_ids = delivery.stems.stem_ids or ("dialogue", "ambience", "sfx")
        canvases = {sid: _blank(total_samples) for sid in stem_ids}
        ordered = sorted(placement.placements, key=lambda p: p.start_seconds)
        changed, seams = apply_transitions(
            timeline,
            {c.cue_id: c.wav_bytes for c in clips},
            stem_for,
            transitions,
            self.sample_rate_hz,
            self.channel_count,
        )
        for cue_id, wav_bytes in changed.items():
            if clip_map[cue_id].stem_id not in canvases:
                raise mix_error("transition stem must exist in delivery layout", MIX_CROSSFADE_INVALID)
            clip_map[cue_id] = MixClip(cue_id, wav_bytes, clip_map[cue_id].stem_id)

        self._render_clips(ordered, clip_map, canvases, stem_ids)
        if bed_wav is not None:
            self._add_bed(bed_wav, canvases, total_samples, duck_bed)
        layer_frames, ducking_summary = apply_layers(
            canvases, layers, self.sample_rate_hz, self.channel_count, layer_ducking
        )
        if routing is not None:
            canvases = routing.process_buses(canvases)

        return self._finish_mix(
            canvases,
            delivery,
            placement,
            seams,
            windows,
            layer_frames,
            ducking_summary,
            getattr(routing, "sidechain_measurements", ()),
        )

    def _finish_mix(
        self, canvases, delivery, placement, seams, windows, layer_frames, ducking_summary, sidechain_measurements
    ):
        declared = placement.timeline_duration_seconds
        stem_wavs = {sid: self._encode(samples) for sid, samples in canvases.items()}
        layout = StemLayout(stem_ids=tuple(sorted(stem_wavs)))
        bundle = build_stem_bundle(layout=layout, stem_wavs=stem_wavs)
        master = recombine_stems(bundle, policy=delivery.recombination)
        measured = len(self._decode(master)) / float(self.sample_rate_hz * self.channel_count)
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
            source_windows=windows,
            layer_source_frames=layer_frames,
            layer_ducking_summary=ducking_summary,
            bus_sidechain_measurements=sidechain_measurements,
        )

    def _decode(self, wav):
        samples, rate, channels = decode_pcm_wav(wav)
        if rate != self.sample_rate_hz or channels != self.channel_count:
            raise mix_error("mix input rate or channel count mismatch", MIX_INPUT_INVALID)
        return samples

    def _encode(self, samples):
        return pcm_to_wav(samples, sample_rate_hz=self.sample_rate_hz, channel_count=self.channel_count)

    def _render_clips(
        self,
        ordered: list[PlacedClip],
        clip_map: dict[str, MixClip],
        canvases: dict[str, array],
        stem_ids: tuple[str, ...],
    ) -> None:
        for placed in ordered:
            clip = clip_map.get(placed.cue_id)
            if clip is None:
                continue
            samples = self._decode(clip.wav_bytes)
            window_n = round(placed.duration_seconds * self.sample_rate_hz) * self.channel_count
            if len(samples) < window_n:
                padded = array("h", samples)
                padded.extend([0] * (window_n - len(samples)))
                samples = padded
            else:
                samples = samples[:window_n]
            start = round(placed.start_seconds * self.sample_rate_hz) * self.channel_count
            stem = placed.stem_id if placed.stem_id in canvases else stem_ids[0]
            _overlay(canvases[stem], samples, start)

    def _add_bed(self, bed_wav: bytes, canvases: dict[str, array], total_samples: int, duck_bed: bool) -> None:
        bed_samples = self._decode(bed_wav)
        if duck_bed and "dialogue" in canvases:
            speech = self._encode(canvases["dialogue"])
            bed_canvas = _blank(total_samples)
            _overlay(bed_canvas, bed_samples, 0)
            bed_full = self._encode(bed_canvas)
            ducked = duck_bed_under_speech(speech, bed_full)
            if "ambience" not in canvases:
                canvases["ambience"] = _blank(total_samples)
            _overlay(canvases["ambience"], self._decode(ducked), 0)
        else:
            if "ambience" not in canvases:
                canvases["ambience"] = _blank(total_samples)
            _overlay(canvases["ambience"], bed_samples, 0)

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
