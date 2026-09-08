"""Send-bearing request admission and combined routed-feature work policy."""

from math import isfinite

from kinocut_sound.limits import MAX_MIX_SENDS, MAX_MIX_ROUTED_FEATURE_WORK_UNITS
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error


def guard_send_rows(routing):
    sends = routing.get("sends", ())
    if not isinstance(sends, (list, tuple)):
        raise mix_error("routing sends must be an array", MIX_INPUT_INVALID)
    if len(sends) > MAX_MIX_SENDS:
        raise mix_error("send count exceeds limit", MIX_OVER_LIMIT)
    for send in sends:
        if not isinstance(send, dict):
            raise mix_error("send must be an object", MIX_INPUT_INVALID)
        if "post_fader" in send and type(send["post_fader"]) is not bool:
            raise mix_error("send post_fader must be an actual boolean", MIX_INPUT_INVALID)
        if "gain_db" in send and (type(send["gain_db"]) not in (int, float) or not isfinite(send["gain_db"])):
            raise mix_error("send gain must be an actual finite number", MIX_INPUT_INVALID)


def check_routed_feature_work(request, routing, automation_windows, layer_frames):
    from kinocut_sound.mix.layer_work import layer_work_units
    from kinocut_sound.public.mix_layer_ducking import check_layer_ducking_work

    work = routing.graph.work_units if request.plan.routing.sends else 0
    if request.plan.routing.sidechains:
        work += routing.sidechain_processor.work_units
    if request.plan.routing.envelopes:
        work += routing.check_work({window.cue_id: window.sample_count for window in automation_windows})
    if request.schema_version == 3:
        if request.layer_ducking is not None:
            work += check_layer_ducking_work(request, layer_frames)
        else:
            work += layer_work_units(
                request.layer_assets,
                layer_frames,
                round(request.plan.authoritative_duration_seconds * request.plan.format.sample_rate_hz),
                request.plan.format.channel_count,
            )
    if work > MAX_MIX_ROUTED_FEATURE_WORK_UNITS:
        raise mix_error("combined routed features exceed work-unit budget", MIX_OVER_LIMIT)
    return work


def validate_send_preflight(request, routing, clips, layer_frames):
    from kinocut_sound.mix._wav import decode_pcm_wav
    from kinocut_sound.mix.source_windows import source_window_bounds

    windows = []
    if request.plan.routing.envelopes:
        cues = {cue.cue_id: cue for cue in request.plan.timeline.cues}
        for clip in clips:
            if routing.bindings[clip.cue_id] not in routing.automation.by_track:
                continue
            samples, rate, channels = decode_pcm_wav(clip.wav_bytes)
            if rate != request.plan.format.sample_rate_hz or channels != request.plan.format.channel_count:
                raise mix_error("send automation source format mismatch", MIX_INPUT_INVALID)
            windows.append(source_window_bounds(cues[clip.cue_id], len(samples) // channels, rate))
            del samples
    return check_routed_feature_work(request, routing, windows, layer_frames)
