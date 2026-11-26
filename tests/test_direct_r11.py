"""Round-11 regression cases for spoken direction.

K11-B1: an independent edit earlier in the sentence hid a later instruction about which part of
the clip to keep ("but keep the ending"), so the plan quietly cut it. K11-B2: ordinary politeness
after a removal instruction ("remove the pauses please") raised a blocking question.
"""

from __future__ import annotations

import pytest


def planned(text, probe=None):
    from kinocut.direct import parse_direction, plan_direction

    return plan_direction(parse_direction(text), probe).to_dict()


PROBE = {"duration": 120, "width": 1920, "height": 1080, "has_audio": True}


@pytest.mark.parametrize(
    "text",
    [
        "make it 30 seconds, louder, but keep the ending",
        "make it a 30 second cut, punchier, keep the last 5 seconds",
    ],
)
def test_round11_a_later_keep_instruction_is_not_hidden(text):
    plan = planned(text, PROBE)

    assert plan["question"], "a clip-selection instruction after an edit must ask, not be dropped"
    assert "video_trim" not in [step["tool"] for step in plan["steps"]]


@pytest.mark.parametrize(
    "text",
    [
        "remove the pauses please",
        "remove silence, please",
        "remove dead air thanks",
        "um remove the pauses please",
    ],
)
def test_round11_politeness_after_a_removal_does_not_ask(text):
    plan = planned(text, PROBE)

    assert plan["question"] is None
    assert [step["tool"] for step in plan["steps"]] == ["video_ai_remove_silence"]


@pytest.mark.parametrize(
    "text",
    ["make it 30 seconds, louder", "make it 30 seconds with captions", "make it 30 seconds, louder, captions"],
)
def test_round11_independent_edits_after_a_length_do_not_ask(text):
    plan = planned(text, PROBE)

    assert plan["question"] is None
    assert "video_trim" in [step["tool"] for step in plan["steps"]]


@pytest.mark.parametrize("text", ["remove the music please", "remove the intro please"])
def test_round11_an_unsupported_removal_still_asks(text):
    plan = planned(text, PROBE)

    assert plan["question"]
