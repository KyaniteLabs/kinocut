"""Bound automation cardinality before nested contract construction."""

from kinocut_sound.limits import (
    MAX_MIX_AUTOMATION_ENVELOPES,
    MAX_MIX_AUTOMATION_POINTS,
    MAX_MIX_AUTOMATION_POINTS_PER_ENVELOPE,
)
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, mix_error


def guard_automation_rows(routing):
    envelopes = routing.get("envelopes", ())
    if not isinstance(envelopes, (list, tuple)):
        raise mix_error("automation envelopes must be an array", MIX_INPUT_INVALID)
    if len(envelopes) > MAX_MIX_AUTOMATION_ENVELOPES:
        raise mix_error("automation envelope count exceeds limit", MIX_OVER_LIMIT)
    count = 0
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            raise mix_error("automation envelope must be an object", MIX_INPUT_INVALID)
        points = envelope.get("points", ())
        if not isinstance(points, (list, tuple)):
            raise mix_error("automation points must be an array", MIX_INPUT_INVALID)
        count += len(points)
        if len(points) > MAX_MIX_AUTOMATION_POINTS_PER_ENVELOPE or count > MAX_MIX_AUTOMATION_POINTS:
            raise mix_error("automation point count exceeds limit", MIX_OVER_LIMIT)
