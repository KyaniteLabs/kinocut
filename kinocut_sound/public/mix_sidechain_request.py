"""Raw sidechain admission and strictly bounded measured-summary verification."""

from math import isfinite

from kinocut_sound.limits import MAX_MIX_SIDECHAINS, MAX_MIX_SIDECHAIN_RECEIPT_BYTES
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error


def guard_sidechain_rows(routing):
    rows = routing.get("sidechains", ())
    if not isinstance(rows, (tuple, list)):
        raise mix_error("sidechains must be an array", MIX_INPUT_INVALID)
    if len(rows) > MAX_MIX_SIDECHAINS:
        raise mix_error("sidechain count exceeds limit", MIX_OVER_LIMIT)
    for row in rows:
        if not isinstance(row, dict):
            raise mix_error("sidechain must be an object", MIX_INPUT_INVALID)
        for key in ("attenuation_db", "attack_ms", "release_ms", "recovery_ms"):
            if key in row and (type(row[key]) not in (int, float) or not isfinite(row[key])):
                raise mix_error("sidechain numeric values must be actual finite numbers", MIX_INPUT_INVALID)


def verify_sidechain_measurements(request, measurements):
    from kinocut_sound.mix.bus_sidechains import sidechain_parameters
    from kinocut_sound.public.mix_layer_ducking import _valid_summary
    from kinocut_sound.public.mix_routing_receipt import bounded_json

    policies = request.plan.routing.sidechains
    if not isinstance(measurements, (list, tuple)) or len(measurements) != len(policies):
        raise mix_error("sidechain measurements must match every controller", "mix_worker_failed")
    bounded_json(measurements, MAX_MIX_SIDECHAIN_RECEIPT_BYTES)
    frames = round(request.plan.authoritative_duration_seconds * request.plan.format.sample_rate_hz)
    for policy, measured in zip(policies, measurements, strict=True):
        if not isinstance(measured, dict) or set(measured) != {"source_bus_id", "target_bus_id", "summary"}:
            raise mix_error("sidechain measurement shape mismatch", "mix_worker_failed")
        if measured["source_bus_id"] != policy.source_bus_id or measured["target_bus_id"] != policy.target_bus_id:
            raise mix_error("sidechain measurement identities mismatch", "mix_worker_failed")
        parameters = sidechain_parameters(policy, request.plan.format.sample_rate_hz)
        if not _valid_summary(measured["summary"], parameters, frames):
            raise mix_error("invalid bus-sidechain measurement summary", "mix_worker_failed")
