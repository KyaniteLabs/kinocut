"""Size-bounded routing evidence retained in the mix archive."""

import json

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.limits import MAX_MIX_RECEIPT_BYTES, MAX_MIX_ROUTING_RECEIPT_BYTES
from kinocut_sound.mix._errors import MIX_OVER_LIMIT, mix_error
from kinocut_sound.public.mix_request_v2 import compile_routing


def bounded_json(value, limit):
    encoded = bytearray()
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), allow_nan=False)
    for text in encoder.iterencode(value):
        chunk = text.encode()
        if len(encoded) + len(chunk) > limit:
            raise mix_error("mix receipt exceeds encoded byte limit", MIX_OVER_LIMIT)
        encoded.extend(chunk)
    return bytes(encoded)


def routed_receipt_bytes(receipt, request, layers=None):
    routing = compile_routing(request).receipt()
    bounded_json(routing, MAX_MIX_ROUTING_RECEIPT_BYTES)
    channels = request.plan.format.channel_count
    frames = receipt["sample_count"]
    receipt.update(
        schema_version=4 if request.schema_version == 3 else 3,
        request_schema_version=request.schema_version,
        channel_count=channels,
        frame_count=frames,
        interleaved_sample_count=frames * channels,
        routing=routing,
    )
    if request.schema_version == 3:
        receipt["layers"] = layers
    return bounded_json(receipt, MAX_MIX_RECEIPT_BYTES)


def verify_routing_receipt(receipt, request):
    channels = request.plan.format.channel_count
    rate = request.plan.format.sample_rate_hz
    frames = round(request.plan.authoritative_duration_seconds * rate)
    expected = {
        "schema_version": 4 if request.schema_version == 3 else 3,
        "request_schema_version": request.schema_version,
        "channel_count": channels,
        "frame_count": frames,
        "sample_count": frames,
        "interleaved_sample_count": frames * channels,
        "sample_rate_hz": rate,
    }
    if any(type(receipt.get(key)) is not int or receipt[key] != value for key, value in expected.items()):
        raise mix_error("routed receipt frame metadata mismatch", "mix_worker_failed")
    actual = receipt.get("routing")
    if not isinstance(actual, dict):
        raise mix_error("routed receipt requires a routing object", "mix_worker_failed")
    bounded_json(actual, MAX_MIX_ROUTING_RECEIPT_BYTES)
    if canonical_digest(actual) != canonical_digest(compile_routing(request).receipt()):
        raise mix_error("routed receipt does not match request processing", "mix_worker_failed")
