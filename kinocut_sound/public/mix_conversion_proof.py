"""Parent proof binds original and derived bytes to every V4 source window."""

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.limits import MAX_MIX_INPUT_BYTES, MAX_MIX_CONVERTED_BYTES
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.mix.source_windows import source_window_bounds
from kinocut_sound.public.mix_automation_receipt import verify_source_windows
from kinocut_sound.public.mix_conversion_manifest import _public_projection, _validate_manifest
from kinocut_sound.public.mix_files import read_asset
from kinocut_sound.public.mix_process import remaining
from kinocut_sound.public.mix_request_v2 import compile_routing


def _check_media(data, media):
    pcm, rate, channels = decode_pcm_wav(data)
    if (len(data), rate, channels, len(pcm)) != (
        media.byte_count,
        media.sample_rate_hz,
        media.channel_count,
        media.frame_count * media.channel_count,
    ):
        raise mix_error("verified conversion media shape mismatch", "mix_worker_failed")


def _verified_conversion_rows(prepared, request, original_root, deadline):
    _validate_manifest(prepared.manifest, request)
    original_total = derived_total = 0
    cues = {cue.cue_id: cue for cue in request.plan.timeline.cues}
    for entry in prepared.manifest.entries:
        remaining(deadline)
        original = read_asset(
            original_root, entry.original.path, entry.original.sha256, MAX_MIX_INPUT_BYTES - original_total
        )
        derived = read_asset(
            prepared.root_fd, entry.derived.path, entry.derived.sha256, MAX_MIX_CONVERTED_BYTES - derived_total
        )
        _check_media(original, entry.original)
        _check_media(derived, entry.derived)
        if entry.mode == "copy" and original != derived:
            raise mix_error("same-rate source copy changed bytes", "mix_worker_failed")
        original_total += len(original)
        derived_total += len(derived)
        del original, derived
        window = None
        if entry.kind == "clip":
            window = source_window_bounds(
                cues[entry.binding_id], entry.derived.frame_count, entry.derived.sample_rate_hz
            )
        remaining(deadline)
        yield entry.kind, entry.binding_id, entry.derived.frame_count, window


def _proof_parts(request, rows):
    layers = tuple(frames for kind, _id, frames, _window in rows if kind == "layer")
    windows = tuple(window for kind, _id, _frames, window in rows if kind == "clip")
    automated = ()
    if request.plan.routing.envelopes:
        routing = compile_routing(request)
        automated = tuple(
            window for window in windows if routing.bindings[window.cue_id] in routing.automation.by_track
        )
    return layers, automated, windows


def _verify_conversion_receipt(receipt, request, prepared, windows):
    actual = receipt.get("source_resampling")
    expected = _public_projection(prepared.manifest, request)
    if not isinstance(actual, dict) or canonical_digest(actual) != canonical_digest(expected):
        raise mix_error("conversion receipt differs from parent evidence", "mix_worker_failed")
    sources = [clip.model_dump(mode="json") for clip in request.clips]
    bed = request.bed.model_dump(mode="json") if request.bed else None
    if canonical_digest({"sources": receipt.get("sources"), "bed": receipt.get("bed")}) != canonical_digest(
        {"sources": sources, "bed": bed}
    ):
        raise mix_error("conversion receipt original bindings mismatch", "mix_worker_failed")
    verify_source_windows(receipt, request, windows)
