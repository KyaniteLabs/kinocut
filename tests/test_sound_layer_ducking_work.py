"""Structural work policy rejects excess before any mix canvas is rendered."""

import pytest

from kinocut_sound.mix._errors import MixError
from kinocut_sound.public.mix_request import load_mix_request
from kinocut_sound.public.mix_layer_ducking import check_layer_ducking_work
from tests.test_sound_public_mix import mix_project  # noqa: F401
from tests.test_sound_static_routing import routed_project  # noqa: F401
from tests.test_sound_layers_public import layered_project  # noqa: F401
from tests.test_sound_layer_ducking_public import ducked_project  # noqa: F401


@pytest.mark.parametrize(
    "loop,muted,channels,expected",
    [
        (False, False, 1, 52928),
        (True, False, 1, 79380),
        (True, False, 2, 158760),
        (False, True, 1, 13234),
    ],
)
def test_independent_sample_visit_counts(ducked_project, loop, muted, channels, expected):  # noqa: F811
    _, payload = ducked_project
    if loop:
        payload["layer_assets"][0].update(fill_mode="loop", crossfade_frames=2)
    payload["layer_assets"][0]["layer"]["muted"] = muted
    if channels == 2:
        payload["plan"]["format"]["channel_layout"] = "stereo"
    assert check_layer_ducking_work(load_mix_request(payload), (4,)) == expected


@pytest.mark.parametrize("margin", [-1, 0, 1])
def test_exact_work_policy_boundary(ducked_project, monkeypatch, margin):  # noqa: F811
    from kinocut_sound.public import mix_layer_ducking

    _, payload = ducked_project
    request = load_mix_request(payload)
    monkeypatch.setattr(mix_layer_ducking, "MAX_LAYER_DUCKING_SAMPLE_VISITS", 52928 + margin)
    if margin < 0:
        with pytest.raises(MixError) as failure:
            check_layer_ducking_work(request, (4,))
        assert failure.value.code == "mix_over_limit"
    else:
        assert check_layer_ducking_work(request, (4,)) == 52928


def test_work_limit_is_enforced_before_renderer(ducked_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_worker, mix_layer_ducking
    from kinocut_sound.public.mix_files import open_root, open_parent, staged_output

    root, request = ducked_project
    monkeypatch.setattr(mix_layer_ducking, "MAX_LAYER_DUCKING_SAMPLE_VISITS", 1)

    def forbidden(*args, **kwargs):
        pytest.fail("over-budget ducking must not enter renderer")

    monkeypatch.setattr(mix_worker.MixRenderer, "render", forbidden)
    with (
        open_root(str(root)) as root_fd,
        open_parent(root_fd, request["output_path"]) as (parent, _),
        staged_output(parent) as (stage, _),
        pytest.raises(MixError) as failure,
    ):
        mix_worker.render_to_stage(request, root_fd, stage)
    assert failure.value.code == "mix_over_limit"


def test_no_duck_admission_does_not_apply_new_work_policy(ducked_project, monkeypatch):  # noqa: F811
    from kinocut_sound.public import mix_layer_ducking

    _, payload = ducked_project
    payload["layer_ducking"] = None
    monkeypatch.setattr(mix_layer_ducking, "MAX_LAYER_DUCKING_SAMPLE_VISITS", 0)
    assert check_layer_ducking_work(load_mix_request(payload), (4,)) == 0
