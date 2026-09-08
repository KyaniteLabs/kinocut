"""Bounded subprocess renderer; only its parent may publish a finished bundle."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import logging
import os
import sys
import zipfile

from kinocut_sound._errors import SoundContractError
from kinocut_sound.limits import MAX_MIX_INPUT_BYTES, MAX_MIX_REQUEST_BYTES
from kinocut_sound.mix import CrossfadeTransition, MixClip, MixRenderer
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.mix.layers import MixLayer, _decode_layer
from kinocut_sound.public.mix_files import read_asset
from kinocut_sound.public.mix_request import check_mix_resources, load_mix_request

logger = logging.getLogger(__name__)


def _sources(request, root_fd):
    clips = []
    consumed = 0
    for clip in request.clips:
        data = read_asset(root_fd, clip.path, clip.sha256, MAX_MIX_INPUT_BYTES - consumed)
        consumed += len(data)
        check_mix_resources(request, consumed)
        clips.append(MixClip(clip.cue_id, data, clip.stem_id))
    bed = None
    if request.bed:
        bed = read_asset(root_fd, request.bed.path, request.bed.sha256, MAX_MIX_INPUT_BYTES - consumed)
        consumed += len(bed)
        check_mix_resources(request, consumed)
    layers = []
    layer_frames = []
    if request.schema_version == 3:
        for item in request.layer_assets:
            data = read_asset(root_fd, item.source.path, item.source.sha256, MAX_MIX_INPUT_BYTES - consumed)
            consumed += len(data)
            check_mix_resources(request, consumed)
            layer = MixLayer(item.layer, data, item.fill_mode, item.crossfade_frames)
            fmt = request.plan.format
            decoded = _decode_layer(
                layer,
                fmt.sample_rate_hz,
                fmt.channel_count,
                round(request.plan.authoritative_duration_seconds * fmt.sample_rate_hz),
            )
            layer_frames.append(len(decoded) // fmt.channel_count)
            del decoded
            layers.append(layer)
        from kinocut_sound.public.mix_layer_ducking import check_layer_ducking_work

        check_layer_ducking_work(request, layer_frames)
    return tuple(clips), bed, tuple(layers)


def _base_receipt(request, result, members, rate, channels, expected):
    receipt = {
        "schema_version": 1,
        "request_hash": request.canonical_id(),
        "plan_hash": request.plan.canonical_id(),
        "artifact_kind": "sound_mix_assembly",
        "mastering_status": "not_applied",
        "human_review_required": True,
        "declared_duration_seconds": result.declared_duration_seconds,
        "measured_duration_seconds": result.measured_duration_seconds,
        "within_tolerance": result.within_tolerance,
        "sample_count": expected,
        "sample_rate_hz": rate,
        "media": {
            name: {"sha256": "sha256:" + hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in sorted(members.items())
        },
        "sources": [c.model_dump(mode="json") for c in request.clips],
        "bed": request.bed.model_dump(mode="json") if request.bed else None,
        "seams": [asdict(event) for event in result.seam_report.events],
        "source_windows": [asdict(window) for window in result.source_windows],
    }
    if channels > 1:
        receipt.update(
            schema_version=2, channel_count=channels, frame_count=expected, interleaved_sample_count=expected * channels
        )
        receipt["source_windows"] = [
            {
                "cue_id": window.cue_id,
                "in_frame": window.in_sample,
                "out_frame": window.out_sample,
                "frame_count": window.sample_count,
                "sample_rate_hz": window.sample_rate_hz,
                "channel_count": channels,
                "interleaved_sample_count": window.sample_count * channels,
            }
            for window in result.source_windows
        ]
    return receipt


def _write_bundle(output_fd, request, result):
    members = {"master.wav": result.master_wav}
    members.update({f"stems/{name}.wav": data for name, data in result.stems.stems.items()})
    rate = request.plan.format.sample_rate_hz
    channels = request.plan.format.channel_count
    expected = round(request.plan.authoritative_duration_seconds * rate)
    for data in members.values():
        samples, actual_rate, actual_channels = decode_pcm_wav(data)
        if actual_rate != rate or actual_channels != channels or len(samples) != expected * channels:
            raise mix_error("mix output shape does not match request", MIX_INPUT_INVALID)
    receipt = _base_receipt(request, result, members, rate, channels, expected)
    if request.schema_version >= 2:
        from kinocut_sound.public.mix_routing_receipt import routed_receipt_bytes

        layers = None
        if request.schema_version == 3:
            from kinocut_sound.public.mix_layer_receipt import layer_evidence

            layers = layer_evidence(request, result.layer_source_frames, result.layer_ducking_summary)
        members["receipt.json"] = routed_receipt_bytes(receipt, request, layers)
    else:
        members["receipt.json"] = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    with os.fdopen(os.dup(output_fd), "wb") as target:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in sorted(members.items()):
                archive.writestr(zipfile.ZipInfo(name), data)
        target.flush()
        os.fsync(target.fileno())
    return {k: receipt[k] for k in ("request_hash", "plan_hash", "sample_count", "within_tolerance")}


def render_to_stage(payload, root, output_fd):
    request = load_mix_request(payload)
    clips, bed, layers = _sources(request, root)
    routing = None
    if request.schema_version >= 2:
        from kinocut_sound.public.mix_request_v2 import compile_routing

        routing = compile_routing(request)
    result = MixRenderer(
        sample_rate_hz=request.plan.format.sample_rate_hz,
        channel_count=request.plan.format.channel_count,
        gap_tolerance_seconds=request.plan.timeline.gap_tolerance_seconds,
    ).render(
        timeline=request.plan.timeline,
        routing=routing,
        layers=layers,
        layer_ducking=request.layer_ducking if request.schema_version == 3 else None,
        clips=clips,
        bed_wav=bed,
        duck_bed=request.duck_bed,
        delivery=request.plan.delivery,
        transitions=tuple(CrossfadeTransition(**t.model_dump()) for t in request.transitions),
    )
    return _write_bundle(output_fd, request, result)


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_MIX_REQUEST_BYTES + 1)
        if len(raw) > MAX_MIX_REQUEST_BYTES:
            raise mix_error("mix worker request exceeds byte limit", MIX_INPUT_INVALID)
        result = render_to_stage(raw.decode(), int(sys.argv[1]), int(sys.argv[2]))
        print(json.dumps({"ok": True, **result}))
        return 0
    except SoundContractError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": str(exc)}))
        return 1
    except Exception as exc:
        logger.warning("mix worker failed (%s)", type(exc).__name__)
        print(json.dumps({"ok": False, "code": "mix_worker_failed", "message": "mix worker failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
