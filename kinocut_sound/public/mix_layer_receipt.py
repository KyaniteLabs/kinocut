"""Layer frame evidence checked against independently verified source bytes."""

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.limits import MAX_MIX_INPUT_BYTES, MAX_MIX_LAYER_RECEIPT_BYTES
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav
from kinocut_sound.mix.layers import fill_plan
from kinocut_sound.public.mix_files import read_asset
from kinocut_sound.public.mix_request import check_mix_resources
from kinocut_sound.public.mix_routing_receipt import bounded_json
from kinocut_sound.world.layers import LayerStack


def layer_evidence(request, source_frames):
    stack = LayerStack(tuple(item.layer for item in request.layer_assets))
    target = round(request.plan.authoritative_duration_seconds * request.plan.format.sample_rate_hz)
    entries = []
    for item, state, frames in zip(request.layer_assets, stack.mix(), source_frames, strict=True):
        entries.append(
            {
                **item.model_dump(mode="json"),
                "audible": state.audible,
                "gain_factor": 10 ** (state.effective_gain_db / 20) if state.audible else 0.0,
                "fill": fill_plan(frames, target, item.fill_mode, item.crossfade_frames),
            }
        )
    evidence = {"algorithm": "ambient_pcm16_sequential_crossfade_v1", "entries": entries}
    bounded_json(evidence, MAX_MIX_LAYER_RECEIPT_BYTES)
    return evidence


def verified_layer_shapes(request, root_fd):
    """Yield small shapes, releasing each decoded source before the next read."""
    cache = {}
    consumed = 0
    for item in request.layer_assets:
        identity = (item.source.path, item.source.sha256)
        if identity not in cache:
            data = read_asset(root_fd, *identity, MAX_MIX_INPUT_BYTES - consumed)
            samples, rate, channels = decode_pcm_wav(data)
            if rate != request.plan.format.sample_rate_hz or channels != request.plan.format.channel_count:
                raise mix_error("verified layer source format mismatch", MIX_INPUT_INVALID)
            cache[identity] = (len(data), len(samples) // channels)
            del data, samples
        size, frames = cache[identity]
        consumed += size
        check_mix_resources(request, consumed)
        yield frames


def verify_layer_receipt(receipt, request, source_frames):
    actual = receipt.get("layers")
    if not isinstance(actual, dict):
        raise mix_error("layer receipt requires an object", "mix_worker_failed")
    bounded_json(actual, MAX_MIX_LAYER_RECEIPT_BYTES)
    expected = layer_evidence(request, source_frames)
    if canonical_digest(actual) != canonical_digest(expected):
        raise mix_error("layer evidence does not match verified source frames", "mix_worker_failed")
