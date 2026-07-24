"""Behavior tests for deterministic safe caption placement (issue #403)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.product.captions import (
    CaptionAppearance,
    CaptionRegion,
    plan_caption_placement,
)


def _region(x: float, y: float, width: float, height: float) -> CaptionRegion:
    return CaptionRegion(x=x, y=y, width=width, height=height)


def _default_appearance() -> CaptionAppearance:
    return CaptionAppearance(font_family="Inter", font_size=42, text_color="#FFFFFF", background_color="#000000")


def test_first_candidate_is_preferred_when_it_is_safe() -> None:
    candidates = [_region(0.0, 0.8, 1.0, 0.1), _region(0.0, 0.4, 1.0, 0.1)]

    placement = plan_caption_placement(candidate_regions=candidates)

    assert placement.status == "ready"
    assert placement.region == candidates[0]
    assert placement.burn_in_requested is False


def test_face_product_and_overlay_exclusions_are_each_avoided() -> None:
    # face: first candidate overlaps the face; second does not
    next_face = plan_caption_placement(
        candidate_regions=[_region(0.0, 0.8, 1.0, 0.1), _region(0.0, 0.55, 1.0, 0.1)],
        face_regions=[_region(0.0, 0.75, 1.0, 0.1)],
    )
    assert next_face.region == _region(0.0, 0.55, 1.0, 0.1)

    # product: middle candidate overlaps the logo; bottom avoids it
    next_product = plan_caption_placement(
        candidate_regions=[_region(0.0, 0.8, 1.0, 0.1), _region(0.0, 0.6, 1.0, 0.1)],
        product_regions=[_region(0.05, 0.78, 0.2, 0.05)],
    )
    assert next_product.region == _region(0.0, 0.6, 1.0, 0.1)

    # platform overlay: top candidate overlaps the overlay; bottom avoids it
    next_overlay = plan_caption_placement(
        candidate_regions=[_region(0.0, 0.9, 1.0, 0.1), _region(0.0, 0.05, 1.0, 0.1)],
        overlay_regions=[_region(0.0, 0.85, 1.0, 0.1)],
    )
    assert next_overlay.region == _region(0.0, 0.05, 1.0, 0.1)


def test_face_product_and_overlay_exclusions_are_combined() -> None:
    candidates = [_region(0.0, 0.9, 1.0, 0.05), _region(0.0, 0.7, 1.0, 0.05), _region(0.0, 0.5, 1.0, 0.05)]

    placement = plan_caption_placement(
        candidate_regions=candidates,
        face_regions=[_region(0.0, 0.88, 1.0, 0.05)],
        product_regions=[_region(0.0, 0.68, 1.0, 0.05)],
    )

    assert placement.region == candidates[2]


def test_edge_touching_is_not_treated_as_overlap() -> None:
    candidate = _region(0.0, 0.9, 0.5, 0.1)
    face = _region(0.5, 0.9, 0.5, 0.1)

    placement = plan_caption_placement(candidate_regions=[candidate], face_regions=[face])

    assert placement.status == "ready"
    assert placement.region == candidate


def test_when_no_candidate_is_safe_placement_blocks_with_actionable_warning() -> None:
    placement = plan_caption_placement(
        candidate_regions=[_region(0.0, 0.8, 1.0, 0.1)],
        face_regions=[_region(0.0, 0.0, 1.0, 1.0)],
        burn_in_requested=True,
    )

    assert placement.status == "blocked"
    assert placement.region is None
    assert placement.warning is not None
    assert placement.warning.startswith("no_safe_caption_region")
    assert placement.burn_in_requested is True


def test_empty_candidate_list_fails_closed() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        plan_caption_placement(candidate_regions=[])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"x": -0.01, "y": 0.0, "width": 0.5, "height": 0.1},  # negative origin
        {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.1},  # zero width (degenerate)
        {"x": 0.0, "y": 0.0, "width": 1.5, "height": 0.1},  # oversized width
        {"x": 0.5, "y": 0.0, "width": 0.6, "height": 0.1},  # out of frame
        {"x": 0.9, "y": 0.0, "width": 0.5, "height": 0.1},  # exclusion out of frame
        {"x": 0.1, "y": 0.1, "width": 0.0, "height": 0.2},  # zero-height degenerate
    ],
)
def test_invalid_and_out_of_frame_regions_are_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        CaptionRegion(**kwargs)


def test_appearance_is_configurable_and_bounded() -> None:
    placement = plan_caption_placement(
        candidate_regions=[_region(0.0, 0.8, 1.0, 0.1)],
        appearance=CaptionAppearance(
            font_family="Roboto Mono", font_size=72, text_color="#FFAA00", background_color="#112233"
        ),
    )
    assert placement.appearance.font_family == "Roboto Mono"
    assert placement.appearance.font_size == 72

    with pytest.raises(ValidationError):
        CaptionAppearance(font_family="", font_size=42, text_color="#FFFFFF", background_color="#000000")
    with pytest.raises(ValidationError):
        CaptionAppearance(font_family="X", font_size=999, text_color="#FFFFFF", background_color="#000000")
    with pytest.raises(ValidationError):
        CaptionAppearance(font_family="X", font_size=42, text_color="white", background_color="#000000")


def test_burn_in_defaults_off_and_can_be_opted_in() -> None:
    default = plan_caption_placement(candidate_regions=[_region(0.0, 0.8, 1.0, 0.1)])
    explicit = plan_caption_placement(candidate_regions=[_region(0.0, 0.8, 1.0, 0.1)], burn_in_requested=True)

    assert default.burn_in_requested is False
    assert explicit.burn_in_requested is True
    assert default.status == explicit.status == "ready"


def test_planner_is_deterministic_across_repeated_calls() -> None:
    candidates = (
        _region(0.0, 0.9, 1.0, 0.05),
        _region(0.0, 0.7, 1.0, 0.05),
        _region(0.0, 0.5, 1.0, 0.05),
    )
    faces = (_region(0.0, 0.88, 1.0, 0.05),)

    first = plan_caption_placement(candidate_regions=candidates, face_regions=faces)
    second = plan_caption_placement(candidate_regions=candidates, face_regions=faces)

    assert first == second
    assert first.model_dump() == second.model_dump()


def test_placement_and_regions_are_deeply_immutable() -> None:
    placement = plan_caption_placement(candidate_regions=[_region(0.0, 0.8, 1.0, 0.1)])

    with pytest.raises(ValidationError):
        placement.region = None  # type: ignore[misc]
    with pytest.raises(ValidationError):
        placement.burn_in_requested = True  # type: ignore[misc]
    replacement = placement.model_copy(update={"burn_in_requested": True})
    assert replacement.burn_in_requested is True
    assert placement.burn_in_requested is False


def test_input_sequences_are_materialized_as_immutable_tuples() -> None:
    candidates = [_region(0.0, 0.8, 1.0, 0.1)]
    faces: list[CaptionRegion] = []

    placement = plan_caption_placement(candidate_regions=candidates, face_regions=faces)

    candidates.clear()
    faces.append(_region(0.0, 0.0, 1.0, 1.0))
    assert placement.status == "ready"
