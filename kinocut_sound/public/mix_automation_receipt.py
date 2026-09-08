"""Compare automation source-window claims with independently verified inputs."""

from kinocut_sound._canonical import canonical_digest
from kinocut_sound.mix._errors import mix_error
from kinocut_sound.mix.source_windows import source_window_bounds
from kinocut_sound.public.mix_request_v2 import compile_routing
from kinocut_sound.public.mix_source_shapes import verified_source_shapes
from kinocut_sound.public.mix_window_receipt import source_window_receipts


def verified_automation_windows(request, root_fd):
    routing = compile_routing(request)
    clips = tuple(clip for clip in request.clips if routing.bindings[clip.cue_id] in routing.automation.by_track)
    cues = {cue.cue_id: cue for cue in request.plan.timeline.cues}
    for clip, frames in zip(clips, verified_source_shapes(clips, request, root_fd), strict=True):
        yield source_window_bounds(cues[clip.cue_id], frames, request.plan.format.sample_rate_hz)


def verify_automation_windows(receipt, request, windows):
    actual = receipt.get("source_windows")
    expected_ids = {clip.cue_id for clip in request.clips}
    if not isinstance(actual, list) or len(actual) != len(expected_ids):
        raise mix_error("automation requires complete source-window evidence", "mix_worker_failed")
    by_id = {}
    for row in actual:
        cue_id = row.get("cue_id") if isinstance(row, dict) else None
        if type(cue_id) is not str or cue_id not in expected_ids or cue_id in by_id:
            raise mix_error("source-window receipt identities mismatch", "mix_worker_failed")
        by_id[cue_id] = row
    expected = source_window_receipts(windows, request.plan.format.channel_count)
    if any(canonical_digest(by_id[row["cue_id"]]) != canonical_digest(row) for row in expected):
        raise mix_error("automation source windows differ from verified inputs", "mix_worker_failed")
    routing = compile_routing(request)
    routing.check_work({window.cue_id: window.sample_count for window in windows})
