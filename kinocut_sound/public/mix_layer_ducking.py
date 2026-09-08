"""Structural ducking work admission and bounded worker-summary verification."""

from math import isfinite

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.limits import MAX_LAYER_DUCKING_SAMPLE_VISITS
from kinocut_sound.mix._errors import MIX_OVER_LIMIT, mix_error
from kinocut_sound.mix.layers import fill_plan
from kinocut_sound.mix.layer_ducking import ducking_parameters
from kinocut_sound.world.layers import LayerStack


def check_layer_ducking_work(request, source_frames):
    if request.layer_ducking is None:
        return 0
    channels = request.plan.format.channel_count
    target = round(request.plan.authoritative_duration_seconds * request.plan.format.sample_rate_hz)
    states = LayerStack(tuple(item.layer for item in request.layer_assets), ducking=request.layer_ducking).mix()
    visits = 0
    for item, state, frames in zip(request.layer_assets, states, source_frames, strict=True):
        fill = fill_plan(frames, target, item.fill_mode, item.crossfade_frames)
        visits += frames * channels
        if state.audible:
            visits += channels * (fill["copies"] * min(frames, target) + 4 * target)
    if not any(state.audible for state in states):
        visits += target * channels
    if visits > MAX_LAYER_DUCKING_SAMPLE_VISITS:
        raise mix_error("layer ducking exceeds sample-visit budget", MIX_OVER_LIMIT)
    return visits


def _valid_summary(summary, parameters, frames):
    integers = (
        "active_frames",
        "activity_runs",
        "completed_releases",
        "max_release_frames",
        "truncated_release_frames",
    )
    floats = ("minimum_gain", "final_gain")
    flags = ("truncated_recovery", "final_detector_active")
    if not isinstance(summary, dict) or set(summary) != {*integers, *floats, *flags, "recovery_status"}:
        return False
    if any(type(summary[key]) is not int or not 0 <= summary[key] <= frames for key in integers):
        return False
    if any(type(summary[key]) is not bool for key in flags):
        return False
    target = 10 ** (-parameters["contract"]["attenuation_db"] / 20)
    if any(
        type(summary[key]) is not float or not isfinite(summary[key]) or not target <= summary[key] <= 1
        for key in floats
    ):
        return False
    active, runs, completed = (summary[key] for key in ("active_frames", "activity_runs", "completed_releases"))
    maximum, truncated = summary["max_release_frames"], summary["truncated_release_frames"]
    inactive = frames - active
    ended_runs = runs - int(summary["final_detector_active"])
    if not completed <= runs <= active or bool(active) != bool(runs):
        return False
    if ended_runs > inactive or completed + bool(truncated) > ended_runs:
        return False
    if maximum != (parameters["release_frames"] if completed else 0) or maximum > parameters["recovery_frames"]:
        return False
    if completed * parameters["release_frames"] + truncated > inactive:
        return False
    if not 0 <= truncated < parameters["release_frames"] or truncated > frames - active:
        return False
    if summary["truncated_recovery"] != bool(truncated) or (truncated and summary["final_detector_active"]):
        return False
    if summary["final_detector_active"] and active == 0:
        return False
    if summary["minimum_gain"] > summary["final_gain"]:
        return False
    if active == 0 and (summary["minimum_gain"] != 1 or summary["final_gain"] != 1 or truncated):
        return False
    if not summary["final_detector_active"] and not truncated and summary["final_gain"] != 1:
        return False
    return summary["recovery_status"] == ("pass" if completed else "not_exercised")


def ducking_evidence(request, summary):
    parameters = ducking_parameters(request.layer_ducking, request.plan.format.sample_rate_hz)
    frames = round(request.plan.authoritative_duration_seconds * request.plan.format.sample_rate_hz)
    if not _valid_summary(summary, parameters, frames):
        raise mix_error("invalid layer ducking measurement summary", "mix_worker_failed")
    return {**parameters, "summary": summary}


def verify_ducking_evidence(request, actual):
    if not isinstance(actual, dict):
        raise mix_error("layer ducking requires measured evidence", "mix_worker_failed")
    expected = ducking_evidence(request, actual.get("summary"))
    if canonical_digest(actual) != canonical_digest(expected):
        raise mix_error("layer ducking metadata differs from request", "mix_worker_failed")
